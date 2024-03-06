# d = ascii("ddd")
# print(type(d), d)
#
# if "dota" == ascii("dota").strip("'"):
#     print("OK")
# else:
#     print("Not OK")
#
# print(int(1) / 3)
#
# ii = [{"a": 2}]
# for i in ii:
#     i["a"] = 100
# print(ii)
import json

d = [{"d": 1}, {"d": 5}, {"d": 5}, {"d": 6}, {"d": 6}]
for i in range(6, 1000):
    d.append({"d": i})
print(d[:0])


# def test(ite: str, hh: list[dict], result: list[list[dict]]):
#     start = hh[0].get(ite)
#     for id, h in enumerate(hh):
#         print(h)
#         print(h.items())
#         value = h.get(ite)
#         if value != start:
#             a, b = hh[:id], hh[id:]
#             print(id)
#             print("b:", b)
#             result.append(a)
#             print(result)
#             return test(ite, b, result)
#         if id == len(hh) - 1:
#             result.append(hh)
#             return result

# print(test("d", d, []))
# for id, dd in enumerate(d):

a = {}
print(json.dumps(a))
if a == dict():
    print("haahha")
