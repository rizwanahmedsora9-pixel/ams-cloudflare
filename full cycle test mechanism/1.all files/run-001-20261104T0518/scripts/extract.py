import re, os, sys, json
from html.parser import HTMLParser

class P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms=[]; self.cur=None; self.stack=[]
        self.buttons=[]; self.modals=[]; self.tables=[]
        self.cur_modal=None; self.cur_table=None
        self.stacktag=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        self.stacktag.append(tag)
        if tag=='form':
            self.cur={'action':a.get('action',''), 'method':(a.get('method') or 'get').lower(), 'id':a.get('id',''), 'fields':[]}
            self.forms.append(self.cur)
        if tag in ('input','select','textarea') and self.cur is not None:
            name=a.get('name') or a.get('id') or ''
            if not name: return
            if name in [f[0] for f in self.cur['fields']]: return
            lbl = a.get('placeholder') or ''
            self.cur['fields'].append((name, tag, a.get('type',''), lbl, a.get('required') is not None, a.get('value','')))
        if tag=='button':
            txt=''
            self._btn={'attrs':a,'text':'', 'type':a.get('type','submit')}
            self.buttons.append(self._btn)
        if tag=='div' and a.get('class') and 'modal' in a.get('class','') and a.get('id'):
            self.modals.append(a.get('id'))
        if tag=='table':
            self.cur_table={'id':a.get('id',''), 'cols':[], 'rows':0}
            self.tables.append(self.cur_table)
        if tag=='th' and self.cur_table is not None:
            self._th=True; self._thbuf=''
        if tag=='tr' and self.cur_table is not None:
            self.cur_table['rows']+=1
    def handle_endtag(self, tag):
        if tag=='form': self.cur=None
        if tag=='th' and getattr(self,'_th',False):
            self.cur_table['cols'].append(self._thbuf.strip()); self._th=False
        if tag=='table': self.cur_table=None
        if tag=='button':
            pass
    def handle_data(self, data):
        d=data.strip()
        if getattr(self,'_th',False): self._thbuf+=data
        if self.buttons and self.buttons[-1]['text']=='' and d:
            self.buttons[-1]['text']=d[:60]

def scan(path):
    s=open(path,encoding='utf-8',errors='ignore').read()
    p=P(); 
    try: p.feed(s)
    except Exception: pass
    fetches=sorted(set(re.findall(r"fetch\(\s*[`'\"]([^`'\"$]{0,80})", s)))
    actions=sorted(set(re.findall(r"action=\"\{\{ ?url_for\('([^']+)'", s)))
    names=sorted(set(re.findall(r"name=\"([a-zA-Z0-9_\-\[\]]+)\"", s)))
    ids=sorted(set(re.findall(r"id=\"([a-zA-Z0-9_\-]+)\"\s", s)))
    return dict(forms=p.forms, buttons=[(b['text'], b['attrs'].get('onclick','')[:60], b['attrs'].get('formaction',''), b['attrs'].get('id','')) for b in p.buttons if b['text'] or b['attrs'].get('onclick')],
                modals=sorted(set(p.modals)), tables=p.tables, fetches=fetches, actions=actions, names=names)

out={}
for root,dirs,files in os.walk('templates'):
    for f in sorted(files):
        if f.endswith('.html'):
            p=os.path.join(root,f)
            out[p]=scan(p)
json.dump(out, open('/tmp/tmpl.json','w'), indent=1)
print(len(out), 'templates scanned')
