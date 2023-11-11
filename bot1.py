"""first attempt connecting to IB"""
import time

from ibapi.client import EClient
from ibapi.wrapper import EWrapper

class IBapi(EWrapper, EClient):
    """Wrapper for IB Client API"""
    def __init__(self):
        EClient.__init__(self, self)

app = IBapi()
app.connect('127.0.0.1', 7496, 80907)
app.run()


time.sleep(2)
app.disconnect()
