from fastapi import Request

from .calibre.write_queue import CalibreWriteQueue


def get_write_queue(request: Request) -> CalibreWriteQueue:
    return request.app.state.write_queue
