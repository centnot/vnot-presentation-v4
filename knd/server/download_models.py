"""Cache only the exact MiniMax H3 files used by the owl workflows."""
import json
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download

BASE = Path('/srv/owl/ComfyUI/models')
REVISION = '54472221d27c695fca9621b0c3ed52f06c4af707'
FILES = [
    'diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors',
    'text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors',
    'vae/minimax_h3_video_vae_fp16.safetensors',
    'vae/minimax_h3_audio_vae_fp32.safetensors',
    'loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors',
    'diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors',
    'loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors',
]
info = HfApi().model_info('Comfy-Org/MiniMax-H3', revision=REVISION, files_metadata=True)
sizes = {file.rfilename:file.size for file in info.siblings}
assert all(file in sizes for file in FILES), 'A named model file is no longer available'
assert sum(sizes[file] for file in FILES) < 110 * 1024 ** 3, 'Unexpected model sizes'
plan = {'revision':info.sha,'bytes':sum(sizes[file] for file in FILES),'files':{file:sizes[file] for file in FILES}}
Path('/srv/owl/logs/model-plan.json').write_text(json.dumps(plan,indent=2))
print(json.dumps(plan),flush=True)
for file in FILES:
    target = BASE / file
    if target.exists() and target.stat().st_size == sizes[file]:
        print('Already cached:',file,flush=True)
        continue
    print('Downloading:',file,flush=True)
    hf_hub_download('Comfy-Org/MiniMax-H3',file,revision=info.sha,local_dir=BASE)
    assert target.stat().st_size == sizes[file],file
    print('Cached:',file,flush=True)
print('All MiniMax H3 models cached.',flush=True)
Path('/srv/owl/logs/models-cached.json').write_text(json.dumps(plan,indent=2))
