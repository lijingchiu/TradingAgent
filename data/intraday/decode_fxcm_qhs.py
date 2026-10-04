"""Inspect/decode existing third-party FXCM QHS5 price archives.

Uses the trusted system ZSTD library and the publisher's checked dictionary.
No downloaded executable is run. Strict filtering leaves source gaps visible;
this mirror is not an execution-quality or complete-validation claim.
"""
from __future__ import annotations
import argparse, ctypes, ctypes.util, csv, datetime as dt, hashlib, importlib.util, json, pathlib, re, struct
ROOT = pathlib.Path(__file__).resolve().parent


def decode(side, start_year, end_year):
    folder = ROOT / 'fxcm_public_mirror'
    raw = (folder / f'eurusd_{side}.qhs5').read_bytes()
    dictionary = bytes(int(x,16) for x in re.findall(r'0x([0-9a-fA-F]{2})\b', (folder / 'xquotes_dictionary_candles_with_volumes.hpp').read_text()))
    assert len(dictionary) == 102400
    library = ctypes.CDLL(ctypes.util.find_library('zstd'))
    library.ZSTD_createDCtx.restype = ctypes.c_void_p
    library.ZSTD_freeDCtx.argtypes = [ctypes.c_void_p]
    library.ZSTD_decompress_usingDict.argtypes = [ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t]
    library.ZSTD_decompress_usingDict.restype = ctypes.c_size_t
    library.ZSTD_isError.argtypes = [ctypes.c_size_t]
    library.ZSTD_isError.restype = ctypes.c_uint
    library.ZSTD_getDictID_fromFrame.argtypes = [ctypes.c_void_p,ctypes.c_size_t]
    library.ZSTD_getDictID_fromFrame.restype = ctypes.c_uint
    offset = struct.unpack_from('<I', raw)[0]
    assert 4 <= offset < len(raw)
    count = struct.unpack_from('<I', raw, offset)[0]
    assert offset + 8 + count * 10 == len(raw)
    assert struct.unpack_from('<I',raw,offset+4+count*10)[0] == 0x13
    context = library.ZSTD_createDCtx()
    rows, invalid, absent, days = [], 0, 0, 0
    try:
        for i in range(count):
            key,length,link = struct.unpack_from('<HII',raw,offset+4+i*10)
            stamp = key * 86400
            year = dt.datetime.fromtimestamp(stamp,dt.timezone.utc).year
            if not start_year <= year <= end_year:
                continue
            assert 4 <= link < offset and link + length <= offset
            frame = raw[link:link+length]
            assert library.ZSTD_getDictID_fromFrame(frame,len(frame)) == 574484007
            output = ctypes.create_string_buffer(28800)
            size = library.ZSTD_decompress_usingDict(context,output,28800,frame,len(frame),dictionary,len(dictionary))
            assert not library.ZSTD_isError(size) and size == 28800
            days += 1
            for minute,(o,h,l,c,v) in enumerate(struct.iter_unpack('<5I',output.raw)):
                if min(o,h,l,c) <= 0:
                    absent += 1
                    continue
                if not l <= min(o,c) <= max(o,c) <= h:
                    invalid += 1
                    continue
                rows.append({'timestamp':dt.datetime.fromtimestamp(stamp+minute*60,dt.timezone.utc).isoformat().replace('+00:00','Z'),
                             'open':o/100000,'high':h/100000,'low':l/100000,'close':c/100000,'volume':v/100000})
    finally:
        library.ZSTD_freeDCtx(context)
    spec = importlib.util.spec_from_file_location('intraday_aggregation',ROOT.parents[1]/'scripts'/'download_intraday_data.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    outputs = {}
    for minutes in (15,5):
        bars, gaps, flat = module.aggregate_minutes(rows,minutes)
        path = ROOT / f'fxcm_mirror_eurusd_{side}_development_{start_year}_{end_year}_m{minutes}.csv'
        module.write_csv(path,bars)
        outputs[f'M{minutes}'] = {'file':path.name,'rows':len(bars),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                'incomplete_blocks_excluded':len(gaps),'zero_volume_blocks_excluded':flat}
    return {'side':side,'decoded_days':days,'valid_minutes':len(rows),'inconsistent_minutes_excluded':invalid,
            'zero_price_missing_minutes':absent,'outputs':outputs}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-year',type=int,default=2015)
    parser.add_argument('--end-year',type=int,default=2019)
    args = parser.parse_args()
    for side in ('bid','ask'):
        print(json.dumps(decode(side,args.start_year,args.end_year),indent=2))
