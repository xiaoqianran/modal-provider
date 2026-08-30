from pathlib import Path
import modal
from modal_world.hyworld2_runtime import hyworld2_worldgen_stage1_image
app=modal.App('tmp-stage4-inspect')
@app.function(image=hyworld2_worldgen_stage1_image,cpu=2,memory=4096,timeout=600)
def inspect():
 p=Path('/opt/HY-World-2.0/hyworld2/worldgen/gen_gs_data.py')
 text=p.read_text()
 for i,line in enumerate(text.splitlines(),1):
  if any(k in line for k in ['cuda','device','torch.', 'split_panorama', 'save_normal', 'moge']):
   print(f'{i}: {line}')
with app.run(): inspect.remote()
