import sys
import os
import pandas as pd
from pathlib import Path
import re
import statistics
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


def save_comparative_boxplot(data_km_5, data_pk8s_5, data_km_10, data_pk8s_10, 
                            data_km_20, data_pk8s_20, filename, directory):
    """
    Create a sensitivity analysis boxplot with 6 boxes (3 parameter values x 2 controllers).
    Shows how metrics vary with parameter values (5, 10, 20) for both controllers.
    """
    # Set professional style
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']
    
    fig, ax = plt.subplots(figsize=(14, 7), constrained_layout=True)
    
    # Prepare data - 6 boxes grouped by parameter value
    all_data = [data_km_5, data_pk8s_5, data_km_10, data_pk8s_10, data_km_20, data_pk8s_20]
    positions = [1, 2, 4, 5, 7, 8]  # Grouped positions
    
    # Scientific colorblind-friendly palette
    color_km = '#42a5f5'   # Blue for kube-manager
    color_pk8s = '#FF8000'  # Orange for preempt-k8s (not too bright)
    colors = [color_km, color_pk8s, color_km, color_pk8s, color_km, color_pk8s]
    
    # Add colored background for parameter groups (gradient based on interfering resources)
    ax.axvspan(0.5, 3, facecolor='#FFE680', alpha=0.5, zorder=0)      # Yellow for 5 (low interference)
    ax.axvspan(3, 6, facecolor='#FFB366', alpha=0.5, zorder=0)        # Orange for 10 (medium interference)
    ax.axvspan(6, 9, facecolor='#FF8FA3', alpha=0.5, zorder=0)        # Pink for 20 (high interference)
    
    # Create boxplot with refined styling and prominent red outliers
    bp = ax.boxplot(all_data, positions=positions, widths=0.7, patch_artist=True,
                    boxprops=dict(linewidth=1.5),
                    whiskerprops=dict(linewidth=1.5),
                    capprops=dict(linewidth=1.5),
                    medianprops=dict(color='#FFFFFF', linewidth=2),
                    flierprops=dict(marker='D', markerfacecolor='#DC143C', markersize=8, 
                                   markeredgecolor='#8B0000', markeredgewidth=1.2, alpha=0.8))
    
    # Color boxes with professional palette - golden edges for all boxes
    for i, patch in enumerate(bp['boxes']):
        patch.set_facecolor(colors[i])
        patch.set_edgecolor('#000000')  # Black edges for all boxes
        patch.set_alpha(0.7)
        patch.set_linewidth(2)
    
    # Style whiskers and caps
    for whisker in bp['whiskers']:
        whisker.set_color('#555555')
        whisker.set_linestyle('-')
        whisker.set_alpha(0.6)
    
    for cap in bp['caps']:
        cap.set_color('#555555')
        cap.set_alpha(0.6)
    
    # Set two-level x-axis labels
    # ax.set_xticks(positions)
    # labels_controller = ['Vanilla K8s', 'Preempt-K8s', 'Vanilla K8s', 'Preempt-K8s', 'Vanilla K8s', 'Preempt-K8s']
    # ax.set_xticklabels(labels_controller, fontsize=20, fontweight='semibold')
    
    # Add vertical separator lines
    ax.axvline(x=3, color='#CCCCCC', linestyle='-', linewidth=1.5, alpha=0.6)
    ax.axvline(x=6, color='#CCCCCC', linestyle='-', linewidth=1.5, alpha=0.6)
    
    # Professional grid styling
    ax.grid(True, axis='y', linestyle='--', alpha=0.3, linewidth=0.8, color='#888888')
    ax.set_axisbelow(True)
    
    # Remove top and right spines (Tufte style)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_linewidth(1.2)
    ax.spines['bottom'].set_linewidth(1.2)
    
    # Labels with improved typography
    # ax.set_ylabel(ylabel, fontsize=14, fontweight='semibold', labelpad=10)
    
    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=color_km, edgecolor=color_km, alpha=0.7, label='Vanilla K8s'),
        Patch(facecolor=color_pk8s, edgecolor=color_pk8s, alpha=0.7, label='Preempt-K8s')
    ]
    ax.legend(handles=legend_elements, loc='upper right', bbox_to_anchor=(1.05, 0.92),
              prop={'size': 20, 'weight': 'semibold'}, framealpha=0.95, edgecolor='gray', fancybox=True)
    
    # Adjust tick label sizes
    ax.tick_params(axis='x', which='both', bottom=False, labelbottom=False)   # Remove x-axis ticks
    ax.tick_params(axis='y', which='major', labelsize=30)  # Set y-axis tick label size
    for label in ax.get_yticklabels():
        label.set_fontweight('semibold')
    
    # Format y-axis to divide values by 1000
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x/1000:.1f}'))
    
    # Add parameter group labels as text annotations at the top of each group
    y_pos = ax.get_ylim()[1] * 0.98  # Near top of plot
    ax.text(1.5, y_pos, '15', ha='center', va='top', 
            fontsize=25, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='white', edgecolor='gray', alpha=0.9, linewidth=1.5))
    ax.text(4.5, y_pos, '30', ha='center', va='top', 
            fontsize=25, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='white', edgecolor='gray', alpha=0.9, linewidth=1.5))
    ax.text(7.5, y_pos, '45', ha='center', va='top', 
            fontsize=25, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='white', edgecolor='gray', alpha=0.9, linewidth=1.5))
    
    # Save as PNG
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

            if len(csv_files) != 30:
                print(f"Error: Expected 30 CSV files for {manager} with {interfering_num} interfering resources, but found {len(csv_files)}|")
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
    
    # Generate boxplots for each metric
    print("\nGenerating boxplots...")
    for metric in metrics:
        data_km_5 = aggregated['kube_manager'][5][metric]
        data_km_10 = aggregated['kube_manager'][10][metric]
        data_km_20 = aggregated['kube_manager'][20][metric]
        data_pk8s_5 = aggregated['preempt_k8s'][5][metric]
        data_pk8s_10 = aggregated['preempt_k8s'][10][metric]
        data_pk8s_20 = aggregated['preempt_k8s'][20][metric]
        
        # Generate the boxplot
        # ylabel = f"{metric.replace('_', ' ').title()} Delays (ms)"
        filename = f"sensitivity_analysis_{metric}.png"
        
        save_comparative_boxplot(
            data_km_5, data_pk8s_5, 
            data_km_10, data_pk8s_10, 
            data_km_20, data_pk8s_20,
            filename, str(output_path)
        )
    
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
