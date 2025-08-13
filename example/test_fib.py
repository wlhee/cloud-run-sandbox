import time
import sys
import os

def fib(n):
    if n < 0:
        return -1
    elif n == 0:
        return 0
    elif n == 1 or n == 2:
        return 1
    else:
        return fib(n-1) + fib(n-2)

if __name__ == "__main__":
    i = 0
    sandbox_id = os.environ.get("CONTAINER_ID")
    prefix = f"[{sandbox_id}] " if sandbox_id else ""
    while True:
        output = f"{prefix}fib({i}) = {fib(i)}"
        print(output, flush=True)
        i += 1
        time.sleep(5)
