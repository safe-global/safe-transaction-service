import gevent
from gunicorn.workers.ggevent import GeventWorker
from psycogreen.gevent import patch_psycopg


class MyGeventWorker(GeventWorker):
    def patch_psycopg2(self):
        patch_psycopg()
        self.log.info("Patched Psycopg2 for gevent")

    def patch(self):
        super().patch()
        self.log.info("Patched all for gevent")
        self.patch_psycopg2()

    def handle_request(self, listener_name, req, sock, addr):
        try:
            with gevent.Timeout(self.cfg.timeout):
                super().handle_request(listener_name, req, sock, addr)
        except gevent.Timeout:
            self.log.error("TimeoutError on %s", req.path)
