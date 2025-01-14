import gevent
from gunicorn.workers.ggevent import GeventWorker


class MyGeventWorker(GeventWorker):
    def handle_request(self, listener_name, req, sock, addr):
        """
        Add timeout for Gunicorn requests
        """
        try:
            with gevent.Timeout(self.cfg.timeout):
                super().handle_request(listener_name, req, sock, addr)
        except gevent.Timeout:
            self.log.error("TimeoutError on %s", req.path)
