import sys
import pandas as pd
from scipy import stats
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


def test(results_20, results_20_monitoring):
    """
    Test Null Hypothesis: There is no significant difference with monitoring enabled.
    
    Args:
        results_20: Path to the 20 interfering resources results directory
        results_20_monitoring: Path to the 20 interfering resources results directory with monitoring enabled
    """
    results_20 = Path(results_20)
    results_20_monitoring = Path(results_20_monitoring)
    
    if not results_20.is_dir() or not results_20_monitoring.is_dir():
        print(f"Error: One or more results path do not exist!")
        sys.exit(1)
    
    # Find all results.csv files in subdirectories
    results_20_csv_files = list(results_20.rglob('*/*.csv'))
    results_20_monitoring_csv_files = list(results_20_monitoring.rglob('*/*.csv'))

    all_results = {
        'no-monitoring': results_20_csv_files,
        'monitoring': results_20_monitoring_csv_files
    }
    
    # Metrics to process
    # metrics = ['mean_latency', 'starts_processing', 'pods_created', 'pods_started']
    metrics = ['mean_latency']
    
    aggregated = {
        'no-monitoring': {},
        'monitoring': {}
    }
    
    # Process all CSV files and calculate aggregated metrics
    for result_type in all_results.keys():
        csv_files = all_results[result_type]
        
        print(f"\nProcessing {result_type} results:")
        print(f"  Found {len(csv_files)} CSV files")

        if len(csv_files) != 30:
            print(f"Error: Expected 30 CSV files for {result_type} results, but found {len(csv_files)}")
            return
        
        # Initialize lists for each metric
        for metric in metrics:
            aggregated[result_type][metric] = []
        
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
                        aggregated[result_type][metric].append(file_mean)
                    else:
                        print(f"Error: metric '{metric}' not found in {csv_file}!")
                        return
                        
            except Exception as e:
                print(f"Error: Failed to read {csv_file}: {e}", file=sys.stderr)
                return
    
    # Execute statistical tests

    alpha = 0.05

    for metric in metrics:
        data_no_monitoring = aggregated['no-monitoring'][metric]
        data_monitoring = aggregated['monitoring'][metric]

        if len(data_no_monitoring) != 30 or len(data_monitoring) != 30:
            print(f"Error: Expected 30 values for each metric, but got {len(data_no_monitoring)} and {len(data_monitoring)} for '{metric}'")
            return
        
        # Check normality of both groups using Shapiro-Wilk test
        _, p_norm1 = stats.shapiro(data_no_monitoring)
        _, p_norm2 = stats.shapiro(data_monitoring)

        if p_norm1 > alpha and p_norm2 > alpha:
            # Both groups are normally distributed
            print(f"Data for metric '{metric}' is normally distributed (p_norm1={p_norm1:.4f} and p_norm2={p_norm2:.4f})")
            normal = True
        else:
            # At least one group is not normally distributed
            print(f"Data for metric '{metric}' is not normally distributed (p_norm1={p_norm1:.4f} and p_norm2={p_norm2:.4f})")
            normal = False
        
        # Check Variances
        _, p_var = stats.levene(data_no_monitoring, data_monitoring)
        if p_var > alpha:
            print(f"Variances for metric '{metric}' are equal (p_var={p_var:.4f})")
            equal_var = True
        else:
            print(f"Variances for metric '{metric}' are not equal (p_var={p_var:.4f})")
            equal_var = False
        
        # Apply the appropriate statistical test based on normality and variance results
        match (normal, equal_var):
            case (True, True):
                # Use Student's t-test
                _, p_value = stats.ttest_ind(data_no_monitoring, data_monitoring, equal_var=True)
                test_used = "Student's t-test"
            case (True, False):
                # Use Welch's t-test
                _, p_value = stats.ttest_ind(data_no_monitoring, data_monitoring, equal_var=False)
                test_used = "Welch's t-test"
            case (False, _):
                # Use Mann-Whitney U test
                _, p_value = stats.mannwhitneyu(data_no_monitoring, data_monitoring, alternative='two-sided')
                test_used = "Mann-Whitney U test"
            
        print(f"  {test_used} p-value for metric '{metric}': {p_value:.4f}")
        if p_value < alpha:
            print(f"  Result: Reject the null hypothesis for metric '{metric}' (significant difference)")
        else:
            print(f"  Result: Fail to reject the null hypothesis for metric '{metric}' (no significant difference)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python monitoring_overhead.py <path-to-20-int> <path-to-20-int-monitoring-enabled>")
        print("Example: python monitoring_overhead.py ./results/20-int ./results/20-int-monitoring-enabled")
        sys.exit(1)
    
    path_20_int = sys.argv[1]
    path_20_int_monitoring = sys.argv[2]

    test(path_20_int, path_20_int_monitoring)
