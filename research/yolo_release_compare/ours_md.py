import re
def parse_md(path):
    pages={};cur=None
    for line in open(path,encoding='utf-8'):
        line=line.rstrip('\n')
        m=re.match(r'#第(\d+)页',line)
        if m: cur=int(m.group(1)); pages[cur]=[]; continue
        if cur is None or not line.strip(): continue
        pages[cur].append(line)
    return pages
def norm_col(line):
    """返回 (字符列表, 阙文数)；[[]]=1 个阙位，记作 '□'；去掉 ^ 和 . 标记；<a|b> 夹注拆成 a+b"""
    s=line.lstrip('^').lstrip('.')
    s=s.replace('[[]]','□')
    s=re.sub(r'<([^>|]*)\|?([^>]*)>',lambda m:m.group(1)+m.group(2),s)
    s=re.sub(r'\[\[([^\]]*)\]\]',r'\1',s)
    return list(s), s.count('□')
