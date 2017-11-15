import hashlib
import sys
import time


def timeit(method):
    def timed(*args, **kw):
        ts = time.time()
        method(*args, **kw)
        te = time.time()
        print('%r  %2.2f ms' % (method.__name__, (te - ts) * 1000))

    return timed


@timeit
def proof_of_work(value, checker):
    nonce = 0
    while(True):
        found_hash1 = hashlib.sha256('{}{}'.format(value, nonce).encode('utf-8')).hexdigest()
        found_hash = hashlib.sha256(found_hash1.encode('utf-8')).hexdigest()
        if found_hash.startswith(checker):
            print('hash = {}\nnonce = {}'.format(found_hash, nonce))
            break
        nonce += 1


if __name__ == '__main__':
    proof_of_work(*sys.argv[1:])
