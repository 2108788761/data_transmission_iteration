path = r'E:\BW\IDEA\data_transmission_iteration\thread.py'
raw = open(path, 'rb').read()
text = raw.decode('gb2312', errors='replace')
if text.startswith('# coding=gb2312'):
    text = '# coding: utf-8\n' + text[len('# coding=gb2312'):].lstrip('\n')
open(path, 'w', encoding='utf-8').write(text)
print('thread.py converted to UTF-8.')