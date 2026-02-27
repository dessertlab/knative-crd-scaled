import sys
import os
import pandas as pd
from pathlib import Path
import re
import statistics
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import numpy as np


def save_aggregated_boxplot(aggregated, metrics, filename, directory):
    """
    Create a single figure containing all metrics' boxplots.
    - `aggregated` is the same structure produced in the script:
      {'kube_manager': {5: {metric: [..]}, 10: {...}, 20: {...}}, 'preempt_k8s': {...}}
    - `metrics` is a list of metric names (order used on x-axis).
    The plot groups boxes by metric; for each metric there are 6 boxes
    (kube_manager and preempt_k8s for loads 5,10,20). Colors represent the load.
    """
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']

    # Create a vertical stack of subplots: one per metric
    loads = [5, 10, 20]
    managers = ['kube_manager', 'preempt_k8s']
    manager_colors = {'kube_manager': '#42a5f5', 'preempt_k8s': '#FF8000'}
    # Hatch patterns per manager (used also in legend)
    manager_hatches = {'kube_manager': '///', 'preempt_k8s': 'xxx'}
    # Hatch patterns per manager (distinct and deterministic)
    manager_hatches = {'kube_manager': '///', 'preempt_k8s': 'xxx'}

    # Wider image with metrics laid out horizontally (each metric in its own column)
    fig, axes = plt.subplots(nrows=1, ncols=len(metrics), figsize=(24, 6), sharey=False, constrained_layout=False)
    # Normalize axes into a flat list of Axes objects
    if isinstance(axes, np.ndarray):
        axes = axes.flatten().tolist()
    elif not isinstance(axes, (list, tuple)):
        axes = [axes]

    # For each metric create a grouped boxplot
    for idx, (ax, metric) in enumerate(zip(axes, metrics)):
        # Build data order and manager sequence: for each load -> kube_manager, preempt_k8s
        all_data = []
        positions = [1, 2, 4, 5, 7, 8]
        manager_seq = []
        for load in loads:
            for manager in managers:
                vals = aggregated.get(manager, {}).get(load, {}).get(metric, [])
                all_data.append(vals)
                manager_seq.append(manager)

        # calculate medians for 20-interference group and print
        km20 = aggregated.get('kube_manager', {}).get(20, {}).get(metric, [])
        pk20 = aggregated.get('preempt_k8s', {}).get(20, {}).get(metric, [])
        if km20 or pk20:
            m_km20 = np.median(km20) if km20 else float('nan')
            m_pk20 = np.median(pk20) if pk20 else float('nan')
            print(f"[{metric}] mediana (20) kube_manager={m_km20:.3f}, preempt_k8s={m_pk20:.3f}")

        bp = ax.boxplot(all_data, positions=positions, widths=0.7, patch_artist=True,
                        boxprops=dict(linewidth=1.2),
                        whiskerprops=dict(linewidth=1.2),
                        capprops=dict(linewidth=1.2),
                        medianprops=dict(color='#FFFFFF', linewidth=2),
                        flierprops=dict(marker='D', markerfacecolor='#DC143C', markersize=6,
                                       markeredgecolor='#8B0000', markeredgewidth=1.0, alpha=0.8))
        
        ax.set_xlim(0.5, 8.5)

        # Apply facecolor and hatch deterministically based on manager_seq
        for patch, mgr in zip(bp['boxes'], manager_seq):
            patch.set_facecolor(manager_colors.get(mgr, '#CCCCCC'))
            patch.set_edgecolor('#000000')
            hatch = manager_hatches.get(mgr, '')
            if hatch:
                patch.set_hatch(hatch)
            patch.set_alpha(0.9)
            patch.set_linewidth(1.2)

        for whisker in bp['whiskers']:
            whisker.set_color('#555555')
            whisker.set_alpha(0.7)
        for cap in bp['caps']:
            cap.set_color('#555555')
            cap.set_alpha(0.7)

        # Remove x-axis ticks and labels as requested
        ax.set_xlim(0.5, 8.5)
        ax.set_xticks([1.5, 4.5, 7.5])
        ax.set_xticklabels(['5 Stressload', '10 Stressload', '20 Stressload'],
                        fontsize=15, ha='center')
        ax.tick_params(axis='x', which='both', bottom=True, labelbottom=True)

        # Keep y-axis in seconds and style it
        ax.tick_params(axis='y', labelsize=30)
        # Ensure y-tick labels are normal weight (not bold)
        for label in ax.get_yticklabels():
            label.set_fontweight('normal')
        ax.set_yscale('linear')
        def smart_formatter(x, p):
            val = x / 1000
            return f'{val:.0f}' if val == int(val) else f'{val:g}'
        ax.yaxis.set_major_formatter(FuncFormatter(smart_formatter))

        # Ensure zero is present on the y-axis (helps compare small values)
        ymin, ymax = ax.get_ylim()
        if ymin > 0:
            ax.set_ylim(0, ymax)

        # Titles per subplot with metric name
        ax.set_title(metric.replace('_', ' ').title(), fontsize=16, fontweight='bold', pad=10)

        # Set y-axis label 'Latencies (s)'. Preferably only on the second subplot,
        # otherwise (if only one subplot) set it there.
        try:
            # Place the 'Latencies (s)' label on the first (leftmost) subplot
            if len(metrics) >= 1 and idx == 0:
                ax.set_ylabel('Latencies (s)', fontsize=16, fontweight='semibold', labelpad=10)
        except Exception:
            # Fallback: set label on current axis if anything unexpected happens
            ax.set_ylabel('Latencies (s)', fontsize=16, fontweight='semibold', labelpad=10)

        # Vertical separators between load blocks (fixed positions)
        ax.axvline(x=3, color='#CCCCCC', linestyle='-', linewidth=1.0, alpha=0.6)
        ax.axvline(x=6, color='#CCCCCC', linestyle='-', linewidth=1.0, alpha=0.6)

        # # Add small load markers (centered above each load block)
        # ylim_top = ax.get_ylim()[1]
        # load_centers = [1.5, 4.5, 7.5]
        # for c, load in zip(load_centers, loads):
        #     ax.text(c, ylim_top * 0.96, f'{load} int', ha='center', va='top',
        #         fontsize=12, fontweight='bold',
        #         bbox=dict(boxstyle='round,pad=0.2', facecolor='white', edgecolor='gray', alpha=0.9, linewidth=0.8))

        # Grid and spines
        ax.grid(True, axis='y', linestyle='--', alpha=0.3)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

    # Create a single horizontal legend below the plots
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=manager_colors['kube_manager'], edgecolor='black', hatch=manager_hatches.get('kube_manager', ''), label='Vanilla K8s'),
        Patch(facecolor=manager_colors['preempt_k8s'], edgecolor='black', hatch=manager_hatches.get('preempt_k8s', ''), label='Preempt-FaaS')
    ]
    # place legend centered below the plots, horizontal (text in bold)
    leg = fig.legend(handles=legend_elements, loc='lower center', ncol=2,
               bbox_to_anchor=(0.5, -0.01), framealpha=0.95, prop={'size':15.5},
               handlelength=3, handleheight=2, borderpad=0.8, labelspacing=0.6)
    for t in leg.get_texts():
        t.set_fontweight('bold')

    # Reduce horizontal spacing between subplots and make room for legend
    plt.subplots_adjust(bottom=0.20, wspace=0.18)

    plot_path_png = os.path.join(directory, filename)
    plt.savefig(plot_path_png, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"Plot saved to: {plot_path_png}")


def parse_value(value):
    """Parse a value with units (e.g., '110.3ms') to float."""
    if pd.isna(value) or value == '':
        return None
    # Remove units like 'ms' and convert to float
    match = re.match(r'([\d.]+)', str(value))
    if match:
        return float(match.group(1))
    return None


def aggregate_results(kube_manager_5_results, kube_manager_10_results, kube_manager_20_results, preempt_k8s_5_results, preempt_k8s_10_results, preempt_k8s_20_results):
    """
    Find all results.csv files in subdirectories and compute averages.
    
    Args:
        kube_manager_5_results: Path to the kube-manager-5 results directory
        kube_manager_10_results: Path to the kube-manager-10 results directory
        kube_manager_20_results: Path to the kube-manager-20 results directory
        preempt_k8s_5_results: Path to the preempt-k8s-5 results directory
        preempt_k8s_10_results: Path to the preempt-k8s-10 results directory
        preempt_k8s_20_results: Path to the preempt-k8s-20 results directory
    """
    kube_manager_5_results = Path(kube_manager_5_results)
    kube_manager_10_results = Path(kube_manager_10_results)
    kube_manager_20_results = Path(kube_manager_20_results)
    preempt_k8s_5_results = Path(preempt_k8s_5_results)
    preempt_k8s_10_results = Path(preempt_k8s_10_results)
    preempt_k8s_20_results = Path(preempt_k8s_20_results)
    
    if not kube_manager_5_results.is_dir() or not kube_manager_10_results.is_dir() or not kube_manager_20_results.is_dir():
        print(f"Error: One or more Kube Manager results path do not exist!")
        sys.exit(1)
    
    if not preempt_k8s_5_results.is_dir() or not preempt_k8s_10_results.is_dir() or not preempt_k8s_20_results.is_dir():
        print(f"Error: One or more Preempt K8s results path do not exist!")
        sys.exit(1)
    
    output_path = Path('./results/sensitivity-analysis')
    if not output_path.exists():
        output_path.mkdir(parents=True)
    
    # Find all results.csv files in subdirectories
    kube_manager_5_csv_files = list(kube_manager_5_results.rglob('*/*.csv'))
    kube_manager_10_csv_files = list(kube_manager_10_results.rglob('*/*.csv'))
    kube_manager_20_csv_files = list(kube_manager_20_results.rglob('*/*.csv'))
    preempt_k8s_5_csv_files = list(preempt_k8s_5_results.rglob('*/*.csv'))
    preempt_k8s_10_csv_files = list(preempt_k8s_10_results.rglob('*/*.csv'))
    preempt_k8s_20_csv_files = list(preempt_k8s_20_results.rglob('*/*.csv'))
    
    all_results = {
        'kube_manager': {
            5: kube_manager_5_csv_files,
            10: kube_manager_10_csv_files,
            20: kube_manager_20_csv_files
        },
        'preempt_k8s': {
            5: preempt_k8s_5_csv_files,
            10: preempt_k8s_10_csv_files,
            20: preempt_k8s_20_csv_files
        }
    }
    
    # Metrics to process
    metrics = ['starts_processing', 'pods_created', 'pods_started']
    
    aggregated = {
        'kube_manager': {5: {}, 10: {}, 20: {}},
        'preempt_k8s': {5: {}, 10: {}, 20: {}}
    }
    
    # Process all CSV files and calculate aggregated metrics
    for manager in all_results.keys():
        for interfering_num in [5, 10, 20]:
            csv_files = all_results[manager][interfering_num]
            
            print(f"\nProcessing {manager} with {interfering_num} interfering resources:")
            print(f"  Found {len(csv_files)} CSV files")

            if len(csv_files) != 10:
                print(f"Error: Expected 10 CSV files for {manager} with {interfering_num} interfering resources, but found {len(csv_files)}|")
                return
            
            # Initialize lists for each metric
            for metric in metrics:
                aggregated[manager][interfering_num][metric] = []
            
            # Process each CSV file and extract metrics
            for csv_file in csv_files:
                try:
                    df = pd.read_csv(csv_file)
                    
                    # For each metric, calculate the mean of the values for all services in this file
                    for metric in metrics:
                        if metric in df.columns:
                            # Convert values from string (with units) to float
                            values = [parse_value(val) for val in df[metric]]
                            # Remove None values
                            values = [v for v in values if v is not None]
                            if len(values) != len(df[metric]):
                                print(f"Error: Some values for metric '{metric}' in {csv_file} could not be parsed and were skipped!")
                                return

                            # Calculate the mean for this file
                            file_mean = statistics.mean(values)
                            aggregated[manager][interfering_num][metric].append(file_mean)
                        else:
                            print(f"Error: metric '{metric}' not found in {csv_file}!")
                            return
                            
                except Exception as e:
                    print(f"Error: Failed to read {csv_file}: {e}", file=sys.stderr)
                    return
    
    # Generate a single aggregated boxplot for all metrics
    print("\nGenerating single aggregated boxplot for all metrics...")
    filename = "sensitivity_analysis_all_metrics.png"
    save_aggregated_boxplot(aggregated, metrics, filename, str(output_path))

    print(f"\nResults saved to {output_path}")



if __name__ == "__main__":
    if len(sys.argv) != 7:
        print("Usage: python " \
        "sensitivity_analysis.py " \
        "<path-to-5-int-kube-manager> <path-to-10-int-kube-manager> <path-to-20-int-kube-manager>" \
        "<path-to-5-int-preempt-k8s> <path-to-10-int-preempt-k8s> <path-to-20-int-preempt-k8s>")
        print("Example: python sensitivity_analysis.py ./results/kube-manager-5 ./results/kube-manager-10 ./results/kube-manager-20 ./results/preempt-k8s-5 ./results/preempt-k8s-10 ./results/preempt-k8s-20")
        sys.exit(1)
    
    path_kube_manager_5 = sys.argv[1]
    path_kube_manager_10 = sys.argv[2]
    path_kube_manager_20 = sys.argv[3]
    path_preempt_k8s_5 = sys.argv[4]
    path_preempt_k8s_10 = sys.argv[5]
    path_preempt_k8s_20 = sys.argv[6]

    aggregate_results(path_kube_manager_5, path_kube_manager_10, path_kube_manager_20, path_preempt_k8s_5, path_preempt_k8s_10, path_preempt_k8s_20)
