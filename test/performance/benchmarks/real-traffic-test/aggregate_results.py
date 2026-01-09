import sys
import pandas as pd
from pathlib import Path
import re
import statistics
import matplotlib.pyplot as plt


def parse_value(value):
    """Parse a value with units (e.g., '110.3ms') to float."""
    if pd.isna(value) or value == '':
        return None
    # Remove units like 'ms' and convert to float
    match = re.match(r'([\d.]+)', str(value))
    if match:
        return float(match.group(1))
    return None


def aggregate_results(base_path):
    """
    Find all results.csv files in subdirectories and compute averages.
    
    Args:
        base_path: Path to the directory to search
    """
    base_path = Path(base_path)
    
    if not base_path.exists():
        print(f"Error: Path '{base_path}' does not exist", file=sys.stderr)
        sys.exit(1)
    
    if not base_path.is_dir():
        print(f"Error: Path '{base_path}' is not a directory", file=sys.stderr)
        sys.exit(1)
    
    # Check if output file already exists
    output_file = base_path / 'results.csv'
    if output_file.exists():
        print(f"Output file '{output_file}' already exists. Skipping aggregation.")
        return
    
    # Find all results.csv files in subdirectories
    csv_files = list(base_path.rglob('*/*.csv'))
    
    if not csv_files:
        print("No results.csv files found in subdirectories", file=sys.stderr)
        sys.exit(1)
    
    print(f"Found {len(csv_files)} results.csv file(s)")
    
    # Read all CSV files and store dataframes
    dataframes = []
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            dataframes.append(df)
        except Exception as e:
            print(f"Warning: Failed to read {csv_file}: {e}", file=sys.stderr)
    
    if not dataframes:
        print("Error: No valid CSV files could be read", file=sys.stderr)
        sys.exit(1)
    
    # Get the first dataframe as template
    result_df = dataframes[0].copy()
    
    # Columns to skip (copy as-is from first file)
    skip_columns = ['service_name', 'criticality_level']
    
    # For each numeric column, compute the average
    numeric_columns = [col for col in result_df.columns if col not in skip_columns]
    
    for col in numeric_columns:
        # Convert column to object type to avoid dtype conflicts
        result_df[col] = result_df[col].astype(object)
        
        values_by_row = {i: [] for i in range(len(result_df))}
        
        # Collect all values for each row across all files
        for df in dataframes:
            for i, value in enumerate(df[col]):
                parsed = parse_value(value)
                if parsed is not None:
                    values_by_row[i].append(parsed)
        
        # Compute average for each row (always as float)
        for i in range(len(result_df)):
            if values_by_row[i]:
                avg_value = sum(values_by_row[i]) / len(values_by_row[i])
                # Get the unit from original value
                original = str(result_df.loc[i, col])
                unit = re.search(r'[a-zA-Z]+$', original)
                if unit:
                    result_df.loc[i, col] = f"{avg_value:.2f}{unit.group()}"
                else:
                    result_df.loc[i, col] = float(f"{avg_value:.2f}")
            # If no valid values, keep original
    
    # Write aggregated results to parent directory
    output_file = base_path / 'results.csv'
    result_df.to_csv(output_file, index=False)
    print(f"Aggregated results written to: {output_file}")
    
    # Generate statistics files for each statistical parameter
    print("\nGenerating statistics files...")
    for col in numeric_columns:
        stats_data = []
        
        # For each service (row)
        for i in range(len(result_df)):
            service_name = result_df.loc[i, 'service_name']
            
            # Collect all values for this service and column across all files
            values = []
            for df in dataframes:
                parsed = parse_value(df.loc[i, col])
                if parsed is not None:
                    values.append(parsed)
            
            if values:
                # Calculate statistics
                mean_val = sum(values) / len(values)
                min_val = min(values)
                max_val = max(values)
                
                if len(values) > 1:
                    variance = statistics.variance(values)
                    std_dev = statistics.stdev(values)
                else:
                    variance = 0.0
                    std_dev = 0.0
                
                # Get unit from original column
                original = str(result_df.loc[i, col])
                unit = re.search(r'[a-zA-Z]+$', original)
                unit_str = unit.group() if unit else ''
                
                stats_data.append({
                    'service_name': service_name,
                    'Mean': f"{mean_val:.2f}{unit_str}" if unit_str else f"{mean_val:.2f}",
                    'Min': f"{min_val:.2f}{unit_str}" if unit_str else f"{min_val:.2f}",
                    'Max': f"{max_val:.2f}{unit_str}" if unit_str else f"{max_val:.2f}",
                    'Variance': f"{variance:.2f}",
                    'Std_Deviation': f"{std_dev:.2f}"
                })
        
        # Write statistics file
        if stats_data:
            stats_df = pd.DataFrame(stats_data)
            stats_file = base_path / f'statistics-{col}.csv'
            stats_df.to_csv(stats_file, index=False)
            print(f"  Created: {stats_file}")
    
    # Generate box-plot for each numeric column
    print("\nGenerating box-plot graphs...")
    
    # Prepare data with service info
    services_info = []
    for i in range(len(result_df)):
        service_name = result_df.loc[i, 'service_name']
        criticality = result_df.loc[i, 'criticality_level']
        services_info.append({
            'index': i,
            'service_name': service_name,
            'criticality_level': criticality,
            'label': f"{service_name} [{i+1}]"
        })
    
    for col in numeric_columns:
        # Collect all values for each service in sorted order
        box_data = []
        labels = []
        
        for service_info in services_info:
            i = service_info['index']
            
            # Collect all values for this service and column across all files
            values = []
            for df in dataframes:
                parsed = parse_value(df.loc[i, col])
                if parsed is not None:
                    values.append(parsed)
            
            if values:
                box_data.append(values)
                labels.append(service_info['label'])
        
        if box_data:
            # Create figure
            fig, ax = plt.subplots(figsize=(12, 6))
            
            # Create box-plot with colors
            bp = ax.boxplot(box_data, labels=labels, patch_artist=True, widths=0.6)
            
            # Color the boxes with glossy effect
            colors = plt.cm.tab20(range(len(box_data)))
            for patch, color in zip(bp['boxes'], colors):
                patch.set_facecolor(color)
                patch.set_alpha(0.8)
                patch.set_edgecolor('black')
                patch.set_linewidth(1.5)
            
            # Style whiskers, caps, and medians
            for whisker in bp['whiskers']:
                whisker.set(linewidth=1.5, linestyle='-', alpha=0.8)
            for cap in bp['caps']:
                cap.set(linewidth=1.5, alpha=0.8)
            for median in bp['medians']:
                median.set(color='darkred', linewidth=2.5)
            for flier in bp['fliers']:
                flier.set(marker='o', markerfacecolor='red', markersize=5, alpha=0.6)
            
            # Add horizontal grid
            ax.yaxis.grid(True, linestyle='--', alpha=0.7)
            ax.set_axisbelow(True)
            
            # Increase y-axis tick density
            ax.yaxis.set_major_locator(plt.MaxNLocator(nbins=15))
            
            # Get unit from column
            sample_value = str(result_df.loc[0, col])
            unit = re.search(r'[a-zA-Z]+$', sample_value)
            unit_str = f" [{unit.group()}]" if unit else ""
            
            # Format column name for title (convert snake_case to Title Case)
            title = col.replace('_', ' ').title()
            
            # Set labels
            ax.set_xlabel('Service [Criticality Level]')
            ax.set_ylabel(f"{title}{unit_str}")
            ax.set_title(f"{title} - Box Plot")
            
            # Rotate x-axis labels for better readability
            plt.xticks(rotation=45, ha='right')
            
            # Adjust layout to prevent label cutoff
            plt.tight_layout()
            
            # Save plot
            plot_file = base_path / f'boxplot-{col}.png'
            plt.savefig(plot_file, dpi=300, bbox_inches='tight')
            plt.close()
            
            print(f"  Created: {plot_file}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python aggregate_results.py <path>")
        print("Example: python aggregate_results.py ./results")
        sys.exit(1)
    
    aggregate_results(sys.argv[1])
