import paramiko
host='5.101.82.46'
user='root'
pwd='wje78laVE8VP'
with open('.ssh-live/amnezia_live.pub','r',encoding='utf-8') as f:
    pub=f.read().strip()
client=paramiko.SSHClient()
client.load_host_keys('.ssh-live/known_hosts')
client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.connect(hostname=host, username=user, password=pwd, look_for_keys=False, allow_agent=False, timeout=20)
commands=[
    "mkdir -p ~/.ssh && chmod 700 ~/.ssh",
    f"grep -qxF '{pub}' ~/.ssh/authorized_keys 2>/dev/null || echo '{pub}' >> ~/.ssh/authorized_keys",
    "chmod 600 ~/.ssh/authorized_keys",
    "tail -n 3 ~/.ssh/authorized_keys"
]
for c in commands:
    stdin, stdout, stderr = client.exec_command(c)
    out = stdout.read().decode('utf-8','ignore').strip()
    err = stderr.read().decode('utf-8','ignore').strip()
    print(f'CMD: {c}')
    if out:
        print(out)
    if err:
        print('ERR:', err)
client.close()
print('KEY_ADDED_OK')
