from pathlib import Path
import modal
from modal_world.hyworld2_runtime import hyworld2_worldgen_stage1_image, HYWORLD2_SOURCE
from modal_world.app import worldgen_outputs

app=modal.App('tmp-stage4-cpu-probe')
@app.function(
    image=hyworld2_worldgen_stage1_image,
    cpu=16.0,
    memory=65536,
    volumes={'/worldgen': worldgen_outputs.with_mount_options(read_only=True)},
    timeout=15*60,
)
def probe(job_id: str):
    import json, os, shutil, subprocess, sys, time
    from pathlib import Path
    source=Path('/worldgen/jobs')/job_id
    target=Path('/tmp/stage4-cpu-probe')
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    for child in source.iterdir():
        if child.name in {'gs_data','gs_smoke_result','stage4.log','stage4_timing.json','stage5_smoke.log','stage5_smoke_timing.json'}:
            continue
        os.symlink(child, target/child.name, target_is_directory=child.is_dir())
    worldgen_root=Path(HYWORLD2_SOURCE)/'hyworld2/worldgen'
    env=os.environ.copy()
    env.update({
        'PYTHONPATH': f'{worldgen_root}:{HYWORLD2_SOURCE}',
        'PYTHONFAULTHANDLER':'1','RANK':'0','LOCAL_RANK':'0','WORLD_SIZE':'1',
        'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','TOKENIZERS_PARALLELISM':'false',
    })
    cmd=[sys.executable,'-X','faulthandler','-u','gen_gs_data.py','--root_path',str(target),'--save_normal','--split_sky']
    t=time.perf_counter()
    cp=subprocess.run(cmd,cwd=worldgen_root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=12*60)
    elapsed=time.perf_counter()-t
    gs=target/'gs_data'
    cams=gs/'cameras.json'
    count=0
    if cams.is_file():
        payload=json.loads(cams.read_text()); count=len([k for k in payload if k not in {'width','height'}])
    return {
        'returncode':cp.returncode,'elapsed_s':round(elapsed,3),'cuda_visible':os.environ.get('CUDA_VISIBLE_DEVICES'),
        'cameras':count,'images':len(list((gs/'images').glob('*.png'))) if gs.exists() else 0,
        'normals':len(list((gs/'normals').glob('*.png'))) if gs.exists() else 0,
        'depths':len(list((gs/'depths').glob('*.png'))) if gs.exists() else 0,
        'points':(gs/'points.ply').is_file(),'tail':cp.stdout[-6000:],
    }

with app.run():
    print(probe.remote('stage12-smoke-20260831'))
