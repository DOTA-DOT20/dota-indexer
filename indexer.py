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

    def _classify_batch_all(self, key: str, remarks: list[dict], result: list[list[dict]]):
        if len(remarks) == 0:
            return result
        start_index = remarks[0][key]
        for id, remark in enumerate(remarks):
            index = remark[key]
            if index != start_index:
                p, l = remarks[:id], remarks[id:]
                result.append(p)
                return self._classify_batch_all(key, l, result)
            if id == len(remarks) - 1:
                result.append(remarks)
                return result

    # Filter the remarks whose p is dot20 obtained in the crawler
    # 1. Filter out illegal ops and ticks (not among supported ops and ticks)
    # 2. Mint (normal and fair modes) and deploy can only have one in a
    # transaction and cannot be in batches and cannot contain other ops.
    # 3. The memo field must be at the last
    # 4. The json field must be legal
    # 5. The tick field must be expressed in ascii
    def _base_filter_extrinsics(self, extrinsics: list[list[dict]]) -> list[list[dict]]:
        res = []
        for extrinsic in extrinsics:
            self.logger.debug(f" #{extrinsic[0]['block_num']},  extrinsic_index {extrinsic[0]['extrinsic_index']}")
            bs = self._classify_batch_all("batchall_index", extrinsic, [])
            is_vail_mint_or_deploy = True
            r = []
            for batch_all in bs:
                self.logger.debug(f"batchall index {batch_all[0]['batchall_index']}, {batch_all}")
                for r_id, remark in enumerate(batch_all):
                    if remark["memo"].get("tick") is not None and isinstance(remark["memo"].get("tick"), str):
                        batch_all[r_id]["memo"]["tick"] = ascii(remark["memo"].get("tick")).lower().strip("'")
                    memo = batch_all[r_id]["memo"]
                    if self.ticks_mode.get(memo.get("tick")) is None:
                        deploy_info = self.dot20.get_deploy_info(memo.get("tick"))
                        if deploy_info is None:
                            if memo.get("op") != self.deploy_op and memo.get("op") != self.memo_op:
                                self.logger.warning(
                                    f"{remark}:\n the tick {memo.get('tick')} has not been deployed, discard the entire batchall: \n {batch_all}")
                                break
                        else:
                            self.ticks_mode[memo.get("tick")] = deploy_info.get("mode")

                    try:
                        if memo.get("op") == self.mint_op and self.ticks_mode[memo.get("tick")] == self.fair_mode:
                            batch_all[r_id]["memo"]["lim"] = 1
                        if memo.get("op") == self.mint_op and memo.get("to") is None:
                            batch_all[r_id]["memo"]["to"] = remark["user"]
                        b_cp = batch_all[r_id].copy()
                        b_cp["memo"] = json.dumps(remark["memo"])
                        self.dot20.fmt_json_data(memo.get("op"), **b_cp)
                    except Exception as e:
                        self.logger.warning(
                            f"{remark}:\n invail json field or value, discard the entire batchall: \n {batch_all} \n{e}")
                        break

                    if memo.get(
                            "op") not in self.supported_ops:
                        self.logger.warning(f"{remark}:\n invail op, discard the entire batchall: \n {batch_all}")
                        break

                    if (memo.get("op") == self.mint_op and self.ticks_mode.get(
                            memo.get("tick")) != self.owner_mode) or \
                            memo.get("op") == self.deploy_op:
                        if len(extrinsic) > 2:
                            is_vail_mint_or_deploy = False
                            self.logger.warning(
                                f"{remark}:\n invail mint or deploy, abandon the entire transaction: \n {extrinsic}")
                            break
                        if len(batch_all) == 2 and batch_all[1]["memo"].get("op") != self.memo_op:
                            is_vail_mint_or_deploy = False
                            self.logger.warning(
                                f"{remark}:\n invail ordinary mint or deploy, abandon the entire transaction: \n {extrinsic}")
                            break

                    if memo.get("op") == "memo" and len(batch_all) > 1:
                        if r_id != len(batch_all) - 1:
                            self.logger.warning(
                                f"{remark}:\n memo is not in the last position, discard the entire batchall:\n {batch_all}")
                            break
                        else:
                            memo_remark = batch_all[-1]["memo"]["text"]
                            batch_all = batch_all[:-1]
                            for bs_item in batch_all:
                                bs_item["memo_remark"] = memo_remark

                    if memo.get("op") == self.memo_op and len(batch_all) == 1:
                        self.logger.warning(
                            f"{remark}:\n There is only one memo field, discard the entire batchall: \n {batch_all}")
                        break
                else:
                    r.append(batch_all)

            if is_vail_mint_or_deploy is False:
                self.logger.warning(f"invail mint, discard the entire transaction:\n {extrinsic}")
            else:
                res.extend(r)
        return res

    # Carry out basic classification of remarks
    # 1. Classify legal mint (normal, fair mode) remarks
    # 2. Classify legal deployment remarks
    # 3. Classify other remarks
    # 4. In a block, one person can only submit one mint (fair and normal mode) remark
    # (regardless of whether it is an agent or multi-signature)
    def _classify_bs(self, bs: list[list[dict]]) -> (Dict[str, list], list[dict], list[dict]):
        unique_user: Dict[str, list[str]] = {}
        mint_remarks: Dict[str, list[dict]] = {}
        deploy_remarks = []
        other_remarks = []
        for batch_all in bs:
            if len(batch_all) == 1:
                memo = batch_all[0]["memo"]
                user = batch_all[0]["origin"]
                tick = str(memo.get("tick"))
                if memo.get("op") == self.mint_op and self.ticks_mode.get(memo.get("tick")) != self.owner_mode:
                    vail_mint_user = unique_user.get(tick) if unique_user.get(tick) is not None else []
                    if user not in vail_mint_user:
                        if mint_remarks.get(tick) is None:
                            mint_remarks[tick] = [batch_all[0]]
                        else:
                            old_rs = mint_remarks.get(tick)
                            old_rs.extend(batch_all)
                            mint_remarks[tick] = old_rs
                        vail_mint_user.append(user)
                        unique_user[tick] = vail_mint_user
                    else:
                        self.logger.warning(f"{batch_all}: \n {user} mint has been submitted in this block")
                elif memo.get("op") == self.deploy_op:
                    deploy_remarks.extend(batch_all)
                else:
                    other_remarks.append(batch_all)
            else:
                other_remarks.append(batch_all)
        self.logger.debug(f"classified mint transactions: {mint_remarks}")
        self.logger.debug(f"classified deploy transactions: {deploy_remarks}")
        self.logger.debug(f"classified other op transactions: {other_remarks}")
        return mint_remarks, deploy_remarks, other_remarks,

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
                        raise Exception(f"{memo} invail entry into another code block")
                    tick = self.dot20.deploy(**item)
                    self.db.create_tables_for_new_tick(tick)
                    self.logger.debug(f"deploy {item} success")
                self.db.session.commit()
            except SQLAlchemyError as e:
                self.logger.error(f"deploy {item} fail：{e}")
                raise e
            except Exception as e:
                self.logger.warning(f"deploy {item} fail：{e}")

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
                        # v["memo"] = json.dumps(memo)
                        self.dot20.mint(**v)
                        self.logger.debug(f"mint {v} success")

                except SQLAlchemyError as e:
                    self.logger.error(f"mint {v} fail：{e}")
                    raise e
                except Exception as e:
                    self.logger.warning(f"mint {v} fail：{e}")

    # Perform other operations
    # 1. Other operations include: transfer, transferFrom, approve, mint (owner)
    # 2. Execute in batchall. Batch atomic operations must be performed in batchall.
    # Failure outside batchall will continue
    def _do_other_ops(self, bs: list[list[dict]]):
        for batch_all in bs:
            try:
                with self.db.session.begin_nested():
                    for b in batch_all:
                        try:
                            b_m = b["memo"]
                            # b["memo"] = json.dumps(b_m)
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
            except Exception as e:
                self.logger.warning(f"{batch_all} fail：{e}")
            self.logger.debug(f"other ops success: {batch_all}")

    # Execute remarks for the entire block
    # 1. Filter remarks first
    # 2. Classification remarks
    # 3. Perform deploy operation
    # 4. Perform mint operation
    # 5. Perform other operations
    # 6. Update indexer_status
    def _execute_remarks_by_per_batchall(self, extrinsics: list[list[dict]]):
        base_filter_res = self._base_filter_extrinsics(extrinsics)
        self.logger.debug(f"filtered extrinsics: {base_filter_res}")
        mint_remarks, deploy_remarks, other_remarks = self._classify_bs(base_filter_res)

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
            self.logger.error(f"Transactions execution failed：{e}")
            raise e

    def run(self):
        while True:
            try:
                latest_block_hash = self.crawler.substrate.get_chain_finalised_head()
                latest_block_num = self.crawler.substrate.get_block_number(latest_block_hash)
                if self.crawler.start_block + self.crawler.delay <= latest_block_num:
                    self.logger.debug(f"block #{self.crawler.start_block}")
                    remarks = self.crawler.get_dota_remarks_by_block_num(self.crawler.start_block)
                    self.logger.debug(f"crawler at block #{self.crawler.start_block} crawled remarks: {remarks}")
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
    # db.drop_all_tick_table("lol")
    # db.drop_all_tick_table("idot")
    # db.drop_all_tick_table("dddd")
    # db.drop_all_tick_table("youw")
    # db.drop_all_tick_table("vdot")

    # db.delete_all_tick_table("dota")

    db.session.commit()
    status = db.get_indexer_status("dot-20")
    start_block = int(os.getenv("START_BLOCK")) if status is None else status[1] + 1
    print(f"start block: {start_block}")
    logger.add("file.log", level="DEBUG", rotation="{} day".format(os.getenv("ROTATION")),
               retention="{} weeks".format(os.getenv("RENTENTION")))
    indexer = Indexer(db, logger, RemarkCrawler(connect_substrate(), int(os.getenv("DELAY_BLOCK")), start_block))
    indexer.run()
