from gevent import monkey; monkey.patch_all()  # noqa

from time import sleep
from bottle import route, run

a = 'original'


@route('/producer')
def producer():
    global a
    a = 'changed'


@route('/consumer')
def consumer():
    sleep(3)
    yield a


run(host='0.0.0.0', port=8080, server='gevent')
