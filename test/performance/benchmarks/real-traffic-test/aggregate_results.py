import sys
import pandas as pd
from pathlib import Path
import re


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
    csv_files = list(base_path.rglob('*/results.csv'))
    
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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python aggregate_results.py <path>")
        print("Example: python aggregate_results.py ./results")
        sys.exit(1)
    
    aggregate_results(sys.argv[1])
