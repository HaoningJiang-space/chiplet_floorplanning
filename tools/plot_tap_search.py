"""Scientific overview of the finite-domain algorithm reference."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--oracle',type=Path,required=True);p.add_argument('--comparison',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    oracle=json.loads(args.oracle.read_text());result=json.loads(args.comparison.read_text())
    fig,axes=plt.subplots(1,3,figsize=(14,4),layout='constrained')
    rows=oracle['rows'];front=sorted(result['pareto'],key=lambda r:r['centre_span_mm'])
    axes[0].scatter([r['centre_span_mm'] for r in rows],[r['peak_c'] for r in rows],s=20,color='#8797a6',alpha=.65,label='77 classes')
    axes[0].plot([r['centre_span_mm'] for r in front],[r['peak_c'] for r in front],'o-',color='#b44235',label='Pareto reference')
    axes[0].set(xlabel='Demand-weighted centre span (mm)',ylabel='Peak temperature (C)',title='Thermal / communication-distance tradeoff')
    axes[0].legend(fontsize=8)
    reference_rise=rows[0]['peak_c']-45
    for method,label,color in [('random','Random','#767676'),('descent','Local descent','#197c78'),('annealing','Annealing','#a16b12')]:
        subset=[r for r in result['summaries'] if r['objective']=='thermal' and r['method']==method]
        budgets=[r['budget'] for r in subset]
        axes[1].plot(budgets,[100*r['optimum_hit_rate'] for r in subset],'o-',label=label,color=color)
        axes[2].plot(budgets,[reference_rise*r['median_gap'] for r in subset],'o-',label=label,color=color)
    axes[1].set(xlabel='Distinct thermal-query budget',ylabel='Optimum hit rate (%)',ylim=(-3,103),title='Thermal objective: 20 seeds / setting')
    axes[2].set(xlabel='Distinct thermal-query budget',ylabel='Median gap to oracle optimum (C)',title='Equal evaluator and query budgets')
    for ax in axes[1:]:ax.set_xticks([8,16,32]);ax.legend(fontsize=8)
    for ax in axes:ax.grid(alpha=.2);ax.spines[['top','right']].set_visible(False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(args.output.with_suffix('.png'),dpi=180)
    fig.savefig(args.output.with_suffix('.pdf'))


if __name__=='__main__':main()
