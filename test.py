
d = ascii("ddd")
print(type(d), d)

if "dota" == ascii("dota").strip("'"):
    print("OK")
else:
    print("Not OK")

print(int(1) / 3)

ii = [{"a": 2}]
for i in ii:
    i["a"] = 100
print(ii)
