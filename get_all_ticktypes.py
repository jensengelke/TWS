"""Print Enum Values"""
from ibapi.ticktype import TickTypeEnum

"""ticktypes"""
for i in range(91):
    print(TickTypeEnum.to_str(i), i)
