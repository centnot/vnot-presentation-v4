# -*- coding: utf-8 -*-
"""Пакетная генерация MiniMax H3 (первый + последний кадр) через ComfyUI без интерфейса.

На сервере:  python owl_run.py jobs_pilot.json            — поставить всё в очередь и дождаться
             python owl_run.py jobs_pilot.json --only ai_flap --bg plate --seeds 1
Локально:    python owl_run.py jobs_pilot.json --dry-run   — только собрать и показать граф

Граф повторяет официальный шаблон video_minimax_h3_i2v (Comfy-Org/workflow_templates),
но без звуковой ветки: CreateVideo получает только кадры, ролик сразу беззвучный.
Недостающие обязательные входы узлов заполняются значениями по умолчанию из /object_info.
Результат: $OWL/out/<scene>/<scene>_<bg>_<WxH>_s<seed>*.mp4 (+ PNG-кадры при "frames": true),
журнал: $OWL/logs/runs.jsonl
"""
import argparse
import json
import os
import pathlib
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding='utf-8')
API = os.environ.get('COMFY', 'http://127.0.0.1:8188')
OWL = pathlib.Path(os.environ.get('OWL', '/srv/owl'))

MODELS = {
    'unet': 'minimax_h3_fl2va_pruned_int8_convrot.safetensors',
    'clip': os.environ.get('TE_FILE', 'qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors'),
    'vae': 'minimax_h3_video_vae_fp16.safetensors',
    'lora': 'minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors',
    'unet_r2v': 'minimax_h3_ref2va_pruned_int8_convrot.safetensors',
    'lora_r2v': 'minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors',
    'audio_vae': 'minimax_h3_audio_vae_fp32.safetensors',
}


def frames_for(seconds, fps=24):
    """Длина как в шаблоне: сетка H3 — 17 кадров на блок, остаток 5."""
    n = max(5, round(seconds * fps))
    return n + (5 - n % 17) % 17


def build_r2v(job, seed, size):
    """Режим «по референсам» (Ref2VA): филин с картинок помещается в сцену из описания."""
    w, h = size
    turbo = job.get('turbo', True)
    steps = job.get('steps', 4 if turbo else 20)
    g = {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': MODELS['unet_r2v'], 'weight_dtype': 'default'}},
        '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': MODELS['clip'], 'type': 'minimax', 'device': 'default'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': MODELS['vae']}},
        '3a': {'class_type': 'VAELoader', 'inputs': {'vae_name': MODELS['audio_vae']}},
    }
    model = ['1', 0]
    if turbo:
        g['4'] = {'class_type': 'LoraLoaderModelOnly',
                  'inputs': {'model': ['1', 0], 'lora_name': MODELS['lora_r2v'], 'strength_model': 1.0}}
        model = ['4', 0]
    r2v = {'clip': ['2', 0], 'vae': ['3', 0], 'audio_vae': ['3a', 0], 'prompt': job['prompt'], 'width': w, 'height': h,
           'length': frames_for(job.get('seconds', 6)), 'ref_image_size': job.get('ref_image_size', 'max')}
    for i, ref in enumerate(job['refs']):
        g[f'r{i}'] = {'class_type': 'LoadImage', 'inputs': {'image': ref}}
        r2v[f'ref_images.ref_image_{i}'] = [f'r{i}', 0]
    tag = f"{job['name']}_{w}x{h}_s{seed}"
    g.update({
        '7': {'class_type': 'MiniMaxH3ReferenceToVideo', 'inputs': r2v},
        '8': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': seed}},
        '9': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'res_multistep'}},
        '10': {'class_type': 'BasicScheduler', 'inputs': {'model': model, 'scheduler': 'simple', 'steps': steps, 'denoise': 1.0}},
        '11': {'class_type': 'BasicGuider', 'inputs': {'model': model, 'conditioning': ['7', 0]}},
        '12': {'class_type': 'SamplerCustomAdvanced', 'inputs': {
            'noise': ['8', 0], 'guider': ['11', 0], 'sampler': ['9', 0], 'sigmas': ['10', 0], 'latent_image': ['7', 1]}},
        '13': {'class_type': 'VAEDecode', 'inputs': {'samples': ['12', 0], 'vae': ['3', 0]}},
        '14': {'class_type': 'CreateVideo', 'inputs': {'images': ['13', 0], 'fps': 24}},
        '15': {'class_type': 'SaveVideo', 'inputs': {'video': ['14', 0], 'filename_prefix': f"{job['name']}/{tag}",
                                                    'format': 'auto', 'codec': 'auto'}},
    })
    return tag, g


def build(job, bg, seed, size):
    w, h = size
    turbo = job.get('turbo', True)
    steps = job.get('steps', 8 if turbo else 20)
    model = ['1', 0]
    g = {
        '1': {'class_type': 'UNETLoader', 'inputs': {'unet_name': MODELS['unet'], 'weight_dtype': 'default'}},
        '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': MODELS['clip'], 'type': 'minimax', 'device': 'default'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': MODELS['vae']}},
        '5': {'class_type': 'LoadImage', 'inputs': {'image': job['keyframes'][bg]['first']}},
        '6': {'class_type': 'LoadImage', 'inputs': {'image': job['keyframes'][bg]['last']}},
    }
    if turbo:
        g['4'] = {'class_type': 'LoraLoaderModelOnly',
                  'inputs': {'model': ['1', 0], 'lora_name': MODELS['lora'], 'strength_model': 1.0}}
        model = ['4', 0]
    tag = f"{job['name']}_{bg}_{w}x{h}_s{seed}"
    g.update({
        '7': {'class_type': 'MiniMaxH3ImageToVideo', 'inputs': {
            'clip': ['2', 0], 'vae': ['3', 0], 'first_frame': ['5', 0], 'last_frame': ['6', 0],
            'prompt': job['prompt'], 'width': w, 'height': h, 'length': frames_for(job.get('seconds', 4))}},
        '8': {'class_type': 'RandomNoise', 'inputs': {'noise_seed': seed}},
        '9': {'class_type': 'KSamplerSelect', 'inputs': {'sampler_name': 'res_multistep'}},
        '10': {'class_type': 'BasicScheduler', 'inputs': {'model': model, 'scheduler': 'simple', 'steps': steps, 'denoise': 1.0}},
        '11': {'class_type': 'BasicGuider', 'inputs': {'model': model, 'conditioning': ['7', 0]}},
        '12': {'class_type': 'SamplerCustomAdvanced', 'inputs': {
            'noise': ['8', 0], 'guider': ['11', 0], 'sampler': ['9', 0], 'sigmas': ['10', 0], 'latent_image': ['7', 1]}},
        '13': {'class_type': 'VAEDecode', 'inputs': {'samples': ['12', 0], 'vae': ['3', 0]}},
        '14': {'class_type': 'CreateVideo', 'inputs': {'images': ['13', 0], 'fps': 24}},
        '15': {'class_type': 'SaveVideo', 'inputs': {'video': ['14', 0], 'filename_prefix': f"{job['name']}/{tag}",
                                                    'format': 'auto', 'codec': 'auto'}},
    })
    if job.get('frames'):
        g['16'] = {'class_type': 'SaveImage', 'inputs': {'images': ['13', 0], 'filename_prefix': f"{job['name']}/frames/{tag}"}}
    return tag, g


def http(path, data=None):
    req = urllib.request.Request(API + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fill_defaults(g, info):
    """Проверяет имена входов по /object_info и дописывает обязательные входы со значениями по умолчанию."""
    for nid, node in g.items():
        spec = info.get(node['class_type'])
        if spec is None:
            raise SystemExit(f"Нет узла {node['class_type']} — обновите ComfyUI")
        req, opt = spec['input'].get('required', {}), spec['input'].get('optional', {})
        for k in node['inputs']:
            if k not in req and k not in opt and k.split('.')[0] not in req and k.split('.')[0] not in opt:
                print(f"  ! {node['class_type']}: неизвестный вход '{k}'")
        for k, v in req.items():
            if k in node['inputs'] or any(x.startswith(k + '.') for x in node['inputs']):
                continue
            kind, meta = v[0], (v[1] if len(v) > 1 else {})
            if isinstance(kind, list):
                node['inputs'][k] = kind[0]
            elif isinstance(meta, dict) and 'default' in meta:
                node['inputs'][k] = meta['default']
            else:
                raise SystemExit(f"{node['class_type']}: обязательный вход '{k}' без значения по умолчанию")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('jobs')
    ap.add_argument('--only', nargs='*')
    ap.add_argument('--bg', nargs='*')
    ap.add_argument('--seeds', type=int)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    cfg = json.loads(pathlib.Path(a.jobs).read_text(encoding='utf-8'))

    plan = []
    for job in cfg['jobs']:
        if a.only and job['name'] not in a.only:
            continue
        if job.get('mode') == 'r2v':
            for size in job.get('sizes', [[1344, 768]]):
                for seed in job.get('seeds', [1])[: a.seeds or None]:
                    plan.append((job['name'], *build_r2v(job, seed, tuple(size))))
            continue
        for bg in job.get('bgs', ['plate']):
            if a.bg and bg not in a.bg:
                continue
            for size in job.get('sizes', [[1344, 768]]):
                for seed in job.get('seeds', [1])[: a.seeds or None]:
                    plan.append((job['name'], *build(job, bg, seed, tuple(size))))
    print(f'заданий: {len(plan)}')
    if a.dry_run:
        print(json.dumps(plan[0][2], ensure_ascii=False, indent=1)[:3000])
        return

    info = http('/object_info')
    log = open(OWL / 'logs' / 'runs.jsonl', 'a', encoding='utf-8')
    for scene, tag, g in plan:
        scene_dir = OWL / 'out' / scene
        if scene_dir.is_dir() and any(p.name.startswith(tag + '_') and p.suffix == '.mp4' for p in scene_dir.iterdir()):
            print(f'{tag}: уже есть, пропуск', flush=True)
            continue
        fill_defaults(g, info)
        t0 = time.time()
        pid = http('/prompt', {'prompt': g, 'client_id': 'owl'})['prompt_id']
        h = None
        while time.time() - t0 < 3600:           # запись в /history появляется, когда задание завершено (успех или ошибка)
            time.sleep(3)
            h = http(f'/history/{pid}').get(pid)
            if h:
                break
        if not h:
            raise SystemExit(f'{tag}: нет результата за час — смотрите $OWL/logs/comfy.log')
        st = h.get('status', {})
        files = [f"{o.get('subfolder', '')}/{o['filename']}" for out in h.get('outputs', {}).values()
                 for key in ('videos', 'images', 'gifs') for o in out.get(key, [])][:3]
        ok = st.get('status_str') == 'success'
        rec = {'tag': tag, 'ok': ok, 'sec': round(time.time() - t0), 'files': files,
               'error': None if ok else json.dumps(st.get('messages', [])[-2:], ensure_ascii=False)[:1500]}
        print(f"{tag}: {'ok' if ok else 'ОШИБКА'} за {rec['sec']} с  {files[:1]}", flush=True)
        log.write(json.dumps(rec, ensure_ascii=False) + '\n'); log.flush()
    print('ГОТОВО', flush=True)


if __name__ == '__main__':
    main()
