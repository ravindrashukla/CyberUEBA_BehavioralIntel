# -*- coding: utf-8 -*-
"""Reconstruct the V-Intelligence defense-in-depth diagram (deck style), 5 layers,
to match the whitepaper structure. Wide banner for a Word figure."""
import textwrap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrow

NAVY='#1F3864'; BLUE='#2E75B6'; TEAL='#1F8A70'; AMBER='#C55A11'; PLUM='#6B2D5C'
INK='#222a31'; WHITE='white'; LGRAY='#EEF1F5'
plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Segoe UI','Arial','DejaVu Sans']})

fig=plt.figure(figsize=(13.6,6.6),dpi=150)
ax=fig.add_axes([0,0,1,1]); ax.set_xlim(0,100); ax.set_ylim(0,100); ax.axis('off')

def rbox(x,y,w,h,fc,ec='none',lw=1.2,rs=1.4):
    ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle=f'round,pad=0,rounding_size={rs}',
                                fc=fc,ec=ec,lw=lw,mutation_aspect=0.55))

# title bar
rbox(0,92,100,8,NAVY,rs=0)
ax.text(3,96,'From Perimeter to Code: Defense in Depth',fontsize=18,fontweight='bold',color='white',va='center')
ax.text(97,96,'V-Intelligence',fontsize=9.5,color='#9DB6D6',va='center',ha='right')

layers=[
 ('LAYER 1','Network & Preemptive','Rigor AI / Preemptive Defense',
  ['Formal math proof of every path','Config drift caught in under an hour','Multi-vendor, agentless'],
  NAVY,'Config Exploits','misconfiguration, shadow rules, drift','No config gap goes unproven'),
 ('LAYER 2','Behavioral & UEBA','V-Intelligence UEBA',
  ['Behavioral digital twin','Trajectory + MITRE direction','4 of 4 nation-state attacks caught'],
  BLUE,'Insider & APT','Volt / Salt Typhoon, living-off-the-land','No behavior goes undetected'),
 ('LAYER 3','Application & API','Behavioral API Protection',
  ['Discover shadow & zombie APIs','Stop bots and logic abuse','Govern AI agent-to-API traffic'],
  TEAL,'API & App Attacks','bot fraud, logic abuse, injection','No API goes unprotected'),
 ('LAYER 4','Data & Agentic Governance','Agentic Data Governance',
  ['Real-time exfiltration detection','Govern AI / LLM data pipelines','Police agent access to data'],
  AMBER,'Data Exfiltration','insider theft, AI / LLM leakage','No data leaves ungoverned'),
 ('LAYER 5','Code & Supply Chain','Mythos + 7-Gate CI/CD',
  ['Secure before deploy','2,000+ zero-days in 7 weeks','Vulnerable code cannot ship'],
  PLUM,'Supply Chain','SolarWinds, Log4Shell, XZ Utils','No vulnerable code ships'),
]
n=len(layers); w=17.2; gap=(100-2*2.5-n*w)/(n-1); x0=2.5
xs=[x0+i*(w+gap) for i in range(n)]
cyt,cyb=58,89   # card top/bottom
for i,(lab,name,prod,pts,color,catch,catchsub,proves) in enumerate(layers):
    x=xs[i]
    rbox(x,cyb-31,w,31,'#FFFFFF',ec=color,lw=1.6)
    rbox(x,cyb-6,w,6,color)                                  # header band
    ax.text(x+w/2,cyb-3,lab,ha='center',va='center',fontsize=9.5,fontweight='bold',color='white')
    ax.text(x+w/2,cyb-9.6,textwrap.fill(name,16),ha='center',va='center',fontsize=10.5,fontweight='bold',color=NAVY,linespacing=1.0)
    ax.text(x+w/2,cyb-15.2,textwrap.fill(prod,20),ha='center',va='center',fontsize=8.6,fontweight='bold',color=color,linespacing=1.0)
    yy=cyb-19.5
    for p in pts:
        ax.text(x+1.1,yy,'•',fontsize=8,color=color,va='top')
        ax.text(x+2.4,yy,textwrap.fill(p,22),fontsize=8,color=INK,va='top',linespacing=1.05)
        yy-=3.4
    # arrow to next
    if i<n-1:
        ax.add_patch(FancyArrow(x+w+0.3,(cyb-15),gap-0.6,0,width=0.7,head_width=3.0,head_length=1.3,
                                length_includes_head=True,fc=color,ec='none'))
    # catch chip
    rbox(x,40,w,12,LGRAY,ec=color,lw=1.0)
    ax.text(x+w/2,48.5,catch,ha='center',va='center',fontsize=8.8,fontweight='bold',color=color)
    ax.text(x+w/2,43.3,textwrap.fill(catchsub,24),ha='center',va='center',fontsize=7.3,color=GRAY if False else INK,linespacing=1.0)

# bottom banner
rbox(2.5,6,95,28,NAVY)
ax.text(50,30,'COUNTERING AI-ENABLED CYBER ATTACKS',ha='center',va='center',fontsize=12.5,fontweight='bold',color='#FFD9A8')
ax.text(50,25.4,'Innovation at every layer fights AI with AI across the full attack surface, under human control.',
        ha='center',va='center',fontsize=9.2,color='white')
for i,(lab,name,prod,pts,color,catch,catchsub,proves) in enumerate(layers):
    x=xs[i]
    ax.text(x+w/2,18.5,f'{lab} proves',ha='center',va='center',fontsize=7.6,fontweight='bold',color='#9DB6D6')
    ax.text(x+w/2,12.8,textwrap.fill(proves,20),ha='center',va='center',fontsize=8.0,color='white',linespacing=1.05)

GRAY='#555f6b'
fig.savefig('docs/_layer_diagram.png',facecolor='white'); plt.close(fig)
print('saved docs/_layer_diagram.png')
