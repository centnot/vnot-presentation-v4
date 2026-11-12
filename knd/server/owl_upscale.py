# -*- coding: utf-8 -*-
"""Увеличение роликов H3 до 1080p через SeedVR2 7B (узлы numz/ComfyUI-SeedVR2_VideoUpscaler) в ComfyUI без интерфейса.

На сервере:  python owl_upscale.py out/ai_flap/ai_flap_plate_1344x768_s11_00001_.mp4 [...] [--res 1080] [--batch 45]
Ролик копируется в $OWL/in, результат — $OWL/out/upscaled/<имя>_1080p_*.mp4, журнал — $OWL/logs/runs.jsonl
"""
import argparse
import json
import pathlib
import shutil
import time

from owl_run import OWL, fill_defaults, http


def graph(name, res, batch):
    return {
        '1': {'class_type': 'LoadVideo', 'inputs': {'file': name}},
        '2': {'class_type': 'GetVideoComponents', 'inputs': {'video': ['1', 0]}},
        '3': {'class_type': 'SeedVR2LoadDiTModel', 'inputs': {'model': 'seedvr2_ema_7b_fp16.safetensors'}},
        '4': {'class_type': 'SeedVR2LoadVAEModel', 'inputs': {'model': 'ema_vae_fp16.safetensors'}},
        '5': {'class_type': 'SeedVR2VideoUpscaler', 'inputs': {
            'image': ['2', 0], 'dit': ['3', 0], 'vae': ['4', 0], 'seed': 42, 'resolution': res,
            'batch_size': batch, 'temporal_overlap': 4, 'color_correction': 'lab'}},
        '6': {'class_type': 'CreateVideo', 'inputs': {'images': ['5', 0], 'fps': 24}},
        '7': {'class_type': 'SaveVideo', 'inputs': {'video': ['6', 0], 'filename_prefix': f'upscaled/{pathlib.Path(name).stem}_{res}p',
                                                   'format': 'auto', 'codec': 'auto'}},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('clips', nargs='+')
    ap.add_argument('--res', type=int, default=1080)
    ap.add_argument('--batch', type=int, default=45)   # 4n+1; больше пачка — ровнее по времени
    a = ap.parse_args()
    info = http('/object_info')
    log = open(OWL / 'logs' / 'runs.jsonl', 'a', encoding='utf-8')
    for clip in a.clips:
        src = (OWL / clip) if not clip.startswith('/') else pathlib.Path(clip)
        shutil.copy2(src, OWL / 'in' / src.name)
        g = graph(src.name, a.res, a.batch)
        fill_defaults(g, info)
        t0 = time.time()
        pid = http('/prompt', {'prompt': g, 'client_id': 'owl-up'})['prompt_id']
        h = None
        while time.time() - t0 < 3600:
            time.sleep(3)
            h = http(f'/history/{pid}').get(pid)
            if h:
                break
        st = (h or {}).get('status', {})
        ok = st.get('status_str') == 'success'
        files = [f"{o.get('subfolder', '')}/{o['filename']}" for out in (h or {}).get('outputs', {}).values()
                 for key in ('videos', 'images') for o in out.get(key, [])][:2]
        rec = {'tag': f'upscale:{src.name}', 'ok': ok, 'sec': round(time.time() - t0), 'files': files,
               'error': None if ok else json.dumps(st.get('messages', [])[-2:], ensure_ascii=False)[:1500]}
        print(f"{src.name} -> {a.res}p: {'ok' if ok else 'ОШИБКА'} за {rec['sec']} с {files[:1]}", flush=True)
        if not ok:
            print(rec['error'])
        log.write(json.dumps(rec, ensure_ascii=False) + '\n'); log.flush()


if __name__ == '__main__':
    main()
