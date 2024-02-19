import json
from dotadb.db import DotaDB
from dotacrawler.crawler import RemarkCrawler
from dot20.dot20 import Dot20
from substrateinterface import SubstrateInterface
from substrateinterface.exceptions import SubstrateRequestException
from typing import Dict
from websocket import WebSocketConnectionClosedException, WebSocketTimeoutException
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv
import os
import time
from logging import Logger
from loguru import logger

load_dotenv()


def connect_substrate() -> SubstrateInterface:
    try:
        url = os.getenv("URL")
        substrate = SubstrateInterface(
            url=url,
        )
        print("connect to {}".format(url))
        print(f"chain: {substrate.chain}, format: {substrate.ss58_format}, token symbol: {substrate.token_symbol}")
        if substrate.chain != os.getenv("CHAIN"):
            raise Exception(f"The connected node is not {os.getenv('CHAIN')}")
    except Exception as e:
        print(f"connect fail {e}, retry...")
        time.sleep(3)
        return connect_substrate()
    return substrate


class Indexer:

    def __init__(self, db: DotaDB, logger: Logger, crawler: RemarkCrawler):
        self.db = db
        self.crawler = crawler
        self.logger = logger
        self.dot20 = Dot20(db, self.crawler.substrate.ss58_format)
        self.supported_ticks = ["dota", "dddd", "idot"]
        self.deploy_op = "deploy"
        self.mint_op = "mint"
        self.transfer_op = "transfer"
        self.transfer_from_op = "transferFrom"
        self.approve_op = "approve"
        self.memo_op = "memo"
        self.supported_ops = [self.deploy_op, self.mint_op, self.transfer_op, self.transfer_from_op, self.approve_op,
                              self.memo_op]
        self.fair_mode = "fair"
        self.owner_mode = "owner"
        self.normal_mode = "normal"
        self.ticks_mode = {"dota": self.fair_mode}

    # Filter the remarks whose p is dot20 obtained in the crawler
    # 1. Filter out illegal ops and ticks (not among supported ops and ticks)
    # 2. Mint (normal and fair modes) and deploy can only have one in a
    # transaction and cannot be in batches and cannot contain other ops.
    # 3. The memo field must be at the last
    # 4. The json field must be legal
    # 5. The tick field must be expressed in ascii
    def _base_filter_remarks(self, remarks: list[dict]) -> list[dict]:
        res = []
        es = []
        extrinsic_index = 0 if len(remarks) == 0 else remarks[0]["extrinsic_index"]
        for remark_id, remark in enumerate(remarks):
            if remark["memo"].get("tick") is not None and isinstance(remark["memo"].get("tick"), str):
                remark["memo"]["tick"] = ascii(remark["memo"].get("tick")).lower().strip("'")

            if remark["extrinsic_index"] == extrinsic_index:
                es.append(remark)

            if extrinsic_index != remark["extrinsic_index"] or remark_id == len(remarks) - 1:
                self.logger.debug(f" #{remark['block_num']},  extrinsic_index {extrinsic_index}")
                bs = []
                btach_all_index = 0 if len(es) == 0 else es[0]["batchall_index"]
                for i, r in enumerate(es):
                    if btach_all_index == r["batchall_index"]:
                        bs.append(r)

                    if btach_all_index != r["batchall_index"] or i == len(es) - 1:
                        self.logger.debug(f"batchall index {btach_all_index}, {bs}")
                        is_vail_mint_or_deploy = True
                        for b_i, b in enumerate(bs):
                            memo = b["memo"]
                            try:
                                b_cp = b.copy()
                                b_cp["memo"] = json.dumps(b["memo"])
                                self.dot20.fmt_json_data(memo.get("op"), **b_cp)
                            except Exception as e:
                                self.logger.warning(f"Illegal json field or value, discard the entire batchall: {e}")
                                break

                            if self.ticks_mode.get(memo.get("tick")) is None:
                                deploy_info = self.dot20.get_deploy_info(memo.get("tick"))
                                if deploy_info is None:
                                    if memo.get("op") != self.deploy_op:
                                        self.logger.warning("Non-deploy op, the tick has not been deployed, discard the entire batchall")
                                        break
                                else:
                                    self.ticks_mode[memo.get("tick")] = deploy_info.get("mode")

                            if memo.get("tick") not in self.supported_ticks or memo.get(
                                    "op") not in self.supported_ops:
                                print(memo.get("tick"), memo.get(
                                    "op"))
                                self.logger.warning("Illegal op or tick, discard the entire batchall")
                                break

                            if (memo.get("op") == self.mint_op and self.ticks_mode.get(
                                    memo.get("tick")) != self.owner_mode) or \
                                    memo.get("op") == self.deploy_op:
                                if len(es) > 2:
                                    is_vail_mint_or_deploy = False
                                    self.logger.warning("Illegal ordinary mint or deploy, abandon the entire transaction")
                                    break
                                if len(bs) == 2 and bs[1]["memo"].get("op") != self.memo_op:
                                    is_vail_mint_or_deploy = False
                                    self.logger.warning("Illegal ordinary mint or deploy, abandon the entire transaction")
                                    break

                            if memo.get("op") == "memo" and len(bs) > 1:
                                if b_i != len(bs) - 1:
                                    print(b_i, len(bs) - 1)
                                    self.logger.warning("memo is not in the last position, discard the entire batchall")
                                    break
                                else:
                                    memo_remark = bs[-1]["text"]
                                    bs = bs[:-1]
                                    for bs_item in bs:
                                        bs_item["memo_remark"] = memo_remark

                            elif memo.get("op") == self.memo_op and len(bs) == 1:
                                self.logger.warning("There is only one memo field, discard the entire batchall")
                                break
                            else:
                                pass

                        else:
                            self.logger.debug(f"filter batchalls :{bs}")
                            res.extend(bs)
                        bs = []
                        btach_all_index = r["batchall_index"]
                        if is_vail_mint_or_deploy is False:
                            self.logger.warning("Illegal mint, discard the entire transaction")
                            break
                es = []
                extrinsic_index = remark["extrinsic_index"]
        return res

    # Carry out basic classification of remarks
    # 1. Classify legal mint (normal, fair mode) remarks
    # 2. Classify legal deployment remarks
    # 3. Classify other remarks
    # 4. In a block, one person can only submit one mint (fair and normal mode) remark
    # (regardless of whether it is an agent or multi-signature)
    def _classify_remarks(self, remarks: list[dict]) -> (Dict[str, list], list[dict], list[dict]):
        unique_user: Dict[str, list[str]] = {}
        mint_remarks: Dict[str, list[dict]] = {}
        extrinsic_index = 0 if len(remarks) == 0 else remarks[0]["extrinsic_index"]
        res = []
        rs = []
        deploy_remarks = []
        for remark_id, remark in enumerate(remarks):
            if extrinsic_index == remark["extrinsic_index"]:
                rs.append(remark)

            if extrinsic_index != remark["extrinsic_index"] or remark_id == len(remarks) - 1:
                if len(rs) == 1:
                    memo = rs[0].get("memo")
                    user = rs[0].get("origin")
                    tick = str(memo.get("tick"))
                    if memo.get("op") == self.mint_op and self.ticks_mode.get(memo.get("tick")) != self.owner_mode:
                        vail_mint_user = unique_user.get(tick) if unique_user.get(tick) is not None else []
                        if user not in vail_mint_user:
                            mint_remarks[tick] = [remark] if mint_remarks.get(tick) is None else \
                                mint_remarks[tick].append(remark)
                            unique_user[tick] = vail_mint_user.append(user)
                        else:
                            self.logger.warning(f"{user} mint has been submitted in this block")
                        rs = []
                    if memo.get("op") == self.deploy_op:
                        deploy_remarks.append(remark)
                        rs = []
                extrinsic_index = remark["extrinsic_index"]
                res.extend(rs)
                rs = []
        self.logger.debug(f"classified mint transactions: {mint_remarks}")
        self.logger.debug(f"classified deploy transactions: {deploy_remarks}")
        self.logger.debug(f"classified other op transactions: {res}")
        return mint_remarks, deploy_remarks, res,

    # Perform deploy operation
    # 1. deploy is executed first, because the deploy operation in the same
    # transaction will generate a new table and cannot be combined with other operations.
    # 2. The deploy operations are executed one by one (not in batches) until all are executed.
    # 3. At the end of each tick deploy, a table corresponding to the tick will be created.
    def _do_deploy(self, deploy_remarks: list[dict]):
        for item in deploy_remarks:
            try:
                with self.db.session.begin():
                    memo = item["memo"]
                    if memo.get("op") != self.deploy_op:
                        raise Exception(f"{memo} Illegal entry into another code block")
                    tick = self.dot20.deploy(**item)
                    self.db.create_tables_for_new_tick(tick)
                    self.logger.debug(f"deploy {item} success")
                self.db.session.commit()
            except SQLAlchemyError as e:
                self.logger.error(f"deploy: {item} fail：{e}")
                raise e
            except Exception as e:
                self.logger.warning(f"deploy: {item} fail：{e}")

    # Perform mint (fair, normal) operation
    # 1. If it is fair mode, the average value will be calculated
    # 2. If the mint operation fails with non-sql, continue directly.
    # 3. If the mint operation fails with sql, break directly (and all operations will be rolled back)
    def _do_mint(self, remarks_dict: Dict[str, list]):
        for item, value in remarks_dict.items():
            deploy_info = self.db.get_deploy_info(item)
            if len(deploy_info) == 0:
                raise Exception(f"{item} Not deployed yet")
            mode = deploy_info[0][11]
            av_amt = 0
            if mode == self.fair_mode:
                amt = deploy_info[0][12]
                av_amt = int(int(amt) / len(value))
            for v_id, v in enumerate(value):
                try:
                    with self.db.session.begin_nested():
                        memo = v["memo"]
                        if mode == self.fair_mode:
                            memo["lim"] = av_amt
                        v["memo"] = json.dumps(memo)
                        self.dot20.mint(**v)
                        self.logger.debug(f"mint: {v} success")

                except SQLAlchemyError as e:
                    self.logger.error(f"mint: {v} fail：{e}")
                    raise e
                except Exception as e:
                    self.logger.warning(f"mint: {v} fail：{e}")

    # Perform other operations
    # 1. Other operations include: transfer, transferFrom, approve, mint (owner)
    # 2. Execute in batchall. Batch atomic operations must be performed in batchall.
    # Failure outside batchall will continue
    def _do_other_ops(self, remarks: list[dict]):
        es = []
        extrinsic_index = 0 if len(remarks) == 0 else remarks[0]["extrinsic_index"]
        for remark_id, remark in enumerate(remarks):

            if extrinsic_index == remark["extrinsic_index"]:
                print(remark_id, remark)
                es.append(remark)
            if extrinsic_index != remark["extrinsic_index"] or remark_id == len(remarks) - 1:
                batchall_index = 0 if len(es) == 0 else es[0]["batchall_index"]
                bs = []
                for b_id, b in enumerate(es):
                    if batchall_index == b["batchall_index"]:
                        bs.append(b)

                    if batchall_index != b["batchall_index"] or b_id == len(es) - 1:
                        try:
                            with self.db.session.begin_nested():
                                for b in bs:
                                    try:
                                        b_m = b["memo"]
                                        b["memo"] = json.dumps(b_m)
                                        if b_m.get("op") == self.deploy_op:
                                            raise Exception(f"enters a code block that does not belong to itself: {b}")
                                        elif b_m.get("op") == self.mint_op and self.ticks_mode.get(
                                                b_m.get("tick")) == self.owner_mode:
                                            self.dot20.mint(**b)
                                        elif b_m.get("op") == self.mint_op and self.ticks_mode.get(
                                                b_m.get("tick")) != self.owner_mode:
                                            raise Exception(f"enters a code block that does not belong to itself: {b}")
                                        elif b_m.get("op") == self.transfer_op:
                                            self.dot20.transfer(**b)
                                        elif b_m.get("op") == self.approve_op:
                                            self.dot20.approve(**b)
                                        elif b_m.get("op") == self.transfer_from_op:
                                            self.dot20.transferFrom(**b)
                                        else:
                                            raise Exception(f"not supported op: {b}")
                                    except Exception as e:
                                        raise e
                        except SQLAlchemyError as e:
                            raise e
                        # except Exception as e:
                        #     pass
                        self.logger.debug(f"batchalls success: {bs}")
                        bs = []
                        batchall_index = b["batchall_index"]
                es = []
                extrinsic_index = remark["extrinsic_index"]

    # Execute remarks for the entire block
    # 1. Filter remarks first
    # 2. Classification remarks
    # 3. Perform deploy operation
    # 4. Perform mint operation
    # 5. Perform other operations
    # 6. Update indexer_status
    def _execute_remarks_by_per_batchall(self, remaks: list[dict]):
        base_filter_res = self._base_filter_remarks(remaks)
        self.logger.debug(f"filtered dot-20 remarks: {base_filter_res}")
        mint_remarks, deploy_remarks, other_remarks = self._classify_remarks(base_filter_res)

        try:
            self.db.session.commit()
            self._do_deploy(deploy_remarks)
            with self.db.session.begin():
                self._do_mint(mint_remarks)
                self._do_other_ops(other_remarks)
                self.db.insert_or_update_indexer_status({"p": "dot-20", "indexer_height": self.crawler.start_block,
                                                         "crawler_height": self.crawler.start_block})
            self.db.session.commit()
        except Exception as e:
            self.logger.error(f"Transactions execution for the entire block failed：{e}")
            raise e

    def run(self):
        while True:
            try:
                latest_block_hash = self.crawler.substrate.get_chain_finalised_head()
                latest_block_num = self.crawler.substrate.get_block_number(latest_block_hash)
                if self.crawler.start_block + self.crawler.delay <= latest_block_num:
                    self.logger.debug(f"crawl  #{self.crawler.start_block} extrinsics")
                    remarks = self.crawler.get_dota_remarks_by_block_num(self.crawler.start_block)
                    self.logger.debug(f"#{self.crawler.start_block} get remarks: {remarks}")
                    self._execute_remarks_by_per_batchall(remarks)
                    self.crawler.start_block += 1
            except (ConnectionError, SubstrateRequestException, WebSocketConnectionClosedException,
                    WebSocketTimeoutException) as e:
                self.logger.warning(f"Disconnected, connecting. . . . {e}")
                try:
                    self.crawler.substrate = connect_substrate()
                except Exception as e:
                    self.logger.warning(f"Disconnected, connecting. . . . {e}")
                time.sleep(3)


if __name__ == "__main__":
    user = os.getenv("MYSQLUSER")
    password = os.getenv("PASSWORD")
    host = os.getenv("HOST")
    database = os.getenv("DATABASE")
    db = DotaDB(db_url=f'mysql+mysqlconnector://{user}:{password}@{host}/{database}')

    # db.drop_all_tick_table("dota")
    # db.delete_all_tick_table("dota")

    db.session.commit()
    status = db.get_indexer_status("dot-20")
    start_block = int(os.getenv("START_BLOCK")) if status is None else status[1] + 1
    print(f"start block: {start_block}")
    logger.add("file.log", level="DEBUG", rotation="{} day".format(os.getenv("ROTATION")),
               retention="{} weeks".format(os.getenv("RENTENTION")))
    indexer = Indexer(db, logger, RemarkCrawler(connect_substrate(), int(os.getenv("DELAY_BLOCK")), start_block))
    indexer.run()
