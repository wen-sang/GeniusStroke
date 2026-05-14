import zlib
import json
import base64

def compress_data(data_obj) -> bytes:
    """
    将 Python 对象 (Dict/List) 转换为 JSON 字符串并压缩
    """
    if data_obj is None:
        return b""
    json_str = json.dumps(data_obj, ensure_ascii=False)
    # 转换为 bytes 并压缩
    compressed = zlib.compress(json_str.encode('utf-8'))
    return compressed

def decompress_data(compressed_bytes: bytes):
    """
    解压 bytes 并还原为 Python 对象
    """
    if not compressed_bytes:
        return None
    try:
        decompressed_str = zlib.decompress(compressed_bytes).decode('utf-8')
        return json.loads(decompressed_str)
    except Exception:
        return None