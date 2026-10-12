"""Rebuild install.py after modifying config.py or runtime modules. Standard Python only."""
from pathlib import Path
import ast
ROOT=Path(__file__).resolve().parents[1]
names=("config.py","vision_core.py","workflow.py","vision_app.py")
files={name:(ROOT/name).read_text(encoding="utf-8-sig") for name in names}
for name,source in files.items(): compile(source,name,"exec")
config={}
for node in ast.parse(files["config.py"]).body:
    if isinstance(node,ast.Assign):
        for target in node.targets:
            if isinstance(target,ast.Name):
                try: config[target.id]=ast.literal_eval(node.value)
                except (ValueError,TypeError): pass
keys=("QR_CAMERA","UART_ENABLE","UART_ID","UART_TX_PIN","UART_RX_PIN","UART_BAUD",
      "PROCESS_SCALE","IDE_PREVIEW","DETECT_PERIOD_MS","QR_SCAN_PERIOD_MS")
head='# 在电脑本地打开并修改这里；在CanMV IDE连接K230后运行一次。\n'
head+='\n'.join('%s = %r'%(key,config[key]) for key in keys)+'\n'
template=(ROOT/"tools/installer_body.txt").read_text(encoding="utf-8")
result=head+'\nimport os\n\nFILES = '+repr(files)+'\n'
result+='LAUNCHER = '+repr((ROOT/"main.py").read_text(encoding="utf-8"))+'\n'
result+='CONFIG_KEYS = '+repr(keys)+'\n'+template
compile(result,"install.py","exec")
(ROOT/"install.py").write_text(result,encoding="utf-8")
print(ROOT/"install.py")
