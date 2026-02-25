import sys
import pandas as pd
from pathlib import Path
import re
import statistics


def parse_value(value):
    """Parse a value with units (e.g., '110.3ms') to float."""
    if pd.isna(value) or value == '':
        return None
    # Remove units like 'ms' and convert to float
    match = re.match(r'([\d.]+)', str(value))
    if match:
        return float(match.group(1))
    return None


def aggregate_results(kube_manager_20_results, preempt_k8s_20_results_5_threads):
    """
    Find all results.csv files in subdirectories and compute averages.
    
    Args:
        kube_manager_20_results: Path to the kube-manager-20 results directory
        preempt_k8s_20_results_5_threads: Path to the preempt-k8s-20-5-threads results directory
    """
    kube_manager_20_results = Path(kube_manager_20_results)
    preempt_k8s_20_results_5_threads = Path(preempt_k8s_20_results_5_threads)
    
    if not kube_manager_20_results.is_dir():
        print(f"Error: Kube Manager 20 results path does not exist!")
        sys.exit(1)
    
    if not preempt_k8s_20_results_5_threads.is_dir():
        print(f"Error: Preempt K8s 20 results 5 threads path does not exist!")
        sys.exit(1)
    
    output_path = Path('./results/sensitivity-analysis')
    if not output_path.exists():
        output_path.mkdir(parents=True)
    
    # Find all results.csv files in subdirectories
    kube_manager_20_csv_files = list(kube_manager_20_results.rglob('*/*.csv'))
    preempt_k8s_20_csv_files = list(preempt_k8s_20_results_5_threads.rglob('*/*.csv'))
    
    all_results = {
        'kube_manager': kube_manager_20_csv_files,
        'preempt_k8s': preempt_k8s_20_csv_files
    }
    
    # Metrics to process
    metrics = ['starts_processing', 'pods_created', 'pods_started']
    
    aggregated = {
        'kube_manager': {},
        'preempt_k8s': {}
    }
    
    # Process all CSV files and calculate aggregated metrics
    for manager in all_results.keys():
        csv_files = all_results[manager]
        
        print(f"\nProcessing {manager} with 20 interfering resources:")
        print(f"  Found {len(csv_files)} CSV files")

        if len(csv_files) != 10:
            print(f"Error: Expected 10 CSV files for {manager} with 20 interfering resources, but found {len(csv_files)}|")
            return
        
        # Initialize lists for each metric
        for metric in metrics:
            aggregated[manager][metric] = []
        
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
                        aggregated[manager][metric].append(file_mean)
                    else:
                        print(f"Error: metric '{metric}' not found in {csv_file}!")
                        return
                        
            except Exception as e:
                print(f"Error: Failed to read {csv_file}: {e}", file=sys.stderr)
                return
    
    # Calculate overall averages for each metric and save to output CSV
    output_file = output_path / 'sensitivity_analysis_5_threads.csv'
    with open(output_file, 'w') as f:
        f.write('manager,metric,average,variance\n')
        for manager in aggregated.keys():
            for metric in metrics:
                if len(aggregated[manager][metric]) > 0:
                    overall_average = statistics.mean(aggregated[manager][metric])
                    variance = statistics.variance(aggregated[manager][metric]) if len(aggregated[manager][metric]) > 1 else 0
                    f.write(f"{manager},{metric},{overall_average},{variance}\n")
                else:
                    print(f"Warning: No valid values found for {manager} - {metric}, skipping average calculation.")
    
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python " \
        "sensitivity_analysis-5-threads.py <path-to-20-int-kube-manager> <path-to-20-int-preempt-k8s-5-threads>")
        print("Example: python sensitivity_analysis-5-threads.py ./results/kube-manager-20 ./results/preempt-k8s-20-5-threads")
        sys.exit(1)
    
    path_kube_manager_20 = sys.argv[1]
    path_preempt_k8s_20_5_threads = sys.argv[2]

    aggregate_results(path_kube_manager_20, path_preempt_k8s_20_5_threads)
