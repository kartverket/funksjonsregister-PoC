#!/usr/bin/env python3
"""
Script to transform function registry CSV data to YAML files.
Each function gets its own YAML file with metadata and child functions.
Uses a team names CSV to map team UUIDs to display names.

Requirements:
PyYAML



Usage:
    Export frisk-data and get funkreg-data.csv and teamnames.csv, then:

    python3 -m venv venv
    source venv/bin/activate
    pip install pyyaml
    python csv_to_yaml.py funkreg.csv output_folder team_names.csv

"""

import csv
import os
import sys
import yaml
from pathlib import Path


def load_team_names(team_csv_file):
    """Load team UUID to name mapping from CSV."""
    team_mapping = {}
    
    with open(team_csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            team_id = row['id']
            team_name = row['displayName']
            
            # Remove the specific prefix "AAD - TF - TEAM -" if present
            # Example: "AAD - TF - TEAM - TEST-NAME-TEAM" -> "TEST-NAME-TEAM"
            prefix = "AAD - TF - TEAM - "
            if team_name.startswith(prefix):
                team_name = team_name[len(prefix):]
            
            team_mapping[team_id] = team_name
    
    print(f"Loaded {len(team_mapping)} team name mappings")
    return team_mapping


def resolve_dependencies(functions):
    """
    Resolve dependency IDs to function names.
    Creates a mapping of ID -> sanitized function name.
    """
    id_to_name = {}
    for func in functions:
        func_id = func['id']
        func_name = sanitize_filename(func['name'])
        id_to_name[func_id] = func_name
    
    # Replace dependency IDs with function names
    for func in functions:
        resolved_deps = []
        for dep_id in func['dependencies']:
            if dep_id in id_to_name:
                resolved_deps.append(id_to_name[dep_id])
            else:
                print(f"  ⚠ Warning: Function '{func['name']}' has dependency ID '{dep_id}' which doesn't exist")
                # Still add it as-is so user knows there's an issue
                resolved_deps.append(dep_id)
        func['dependencies'] = resolved_deps


def sanitize_filename(name):
    """Convert function name to a valid filename."""
    # Replace spaces and special characters with hyphens
    filename = name.lower().replace(' ', '-')
    # Remove any characters that aren't alphanumeric or hyphens
    filename = ''.join(c for c in filename if c.isalnum() or c == '-')
    # Remove consecutive hyphens
    filename = '-'.join(filter(None, filename.split('-')))
    return filename


def find_child_functions(current_path, all_functions):
    """
    Find direct child functions based on path hierarchy.
    A child has a path that starts with the parent path and has exactly one more level.
    
    Example: 
    - Parent: "1.4" -> Children: "1.4.5", "1.4.6", "1.4.7"
    - Parent: "1.4.5" -> Children: "1.4.5.9"
    """
    children = []
    current_depth = len(current_path.split('.'))
    
    for func in all_functions:
        func_path = func['path']
        # Check if this path starts with current_path and is exactly one level deeper
        if func_path.startswith(current_path + '.'):
            func_depth = len(func_path.split('.'))
            if func_depth == current_depth + 1:
                children.append(sanitize_filename(func['name']))
    
    return children


def read_csv_data(csv_file):
    """Read the CSV file and return a list of function dictionaries."""
    functions = []
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse dependencies - split by comma if multiple, otherwise make a list
            dependencies_str = row.get('dependencies', '').strip()
            dependencies = []
            if dependencies_str:
                # Split by comma and strip whitespace
                dependencies = [dep.strip() for dep in dependencies_str.split(',') if dep.strip()]
            
            functions.append({
                'id': row['id'],
                'name': row['name'],
                'path': row['path'],
                'team': row['team'],
                'beskrivelse': row['beskrivelse'],
                'kritikalitet': row.get('kritikalitet', ''),
                'dependencies': dependencies
            })
    
    return functions


def create_yaml_structure(function, child_functions):
    """Create the YAML structure for a function."""
    yaml_data = {
        'apiVersion': 'kartverket.dev/v1alpha1',
        'kind': 'Function',
        'metadata': {
            'name': function['name'],
            'description': function['beskrivelse'] if function['beskrivelse'] else ''
        },
        'spec': {
            'owner': function['team'],
            'criticality': function['kritikalitet'] if function['kritikalitet'] else '',
            'childFunctions': child_functions,
            'dependsOn': function['dependencies']
        }
    }
    
    return yaml_data


def write_combined_yaml_file(all_yaml_data, output_dir, filename='example.yaml'):
    """Write all YAML data to a single file with --- separators."""
    filepath = output_dir / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        for i, yaml_data in enumerate(all_yaml_data):
            if i > 0:
                f.write('\n---\n')
            yaml.dump(yaml_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    return filepath


def main():
    # Check command-line arguments
    if len(sys.argv) != 4:
        print("Usage: python csv_to_yaml.py input.csv output_folder team_names.csv")
        print("\nExample:")
        print("  python csv_to_yaml.py funkreg_data.csv ./functions teamNames.csv")
        sys.exit(1)
    
    # Get arguments
    csv_file = sys.argv[1]
    output_dir = Path(sys.argv[2])
    team_csv_file = sys.argv[3]
    
    # Validate CSV files exist
    if not os.path.exists(csv_file):
        print(f"Error: CSV file '{csv_file}' not found")
        sys.exit(1)
    
    if not os.path.exists(team_csv_file):
        print(f"Error: Team names CSV file '{team_csv_file}' not found")
        sys.exit(1)
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load team names mapping
    print(f"Loading team names from: {team_csv_file}")
    team_mapping = load_team_names(team_csv_file)
    print()
    
    # Read CSV data
    print(f"Reading CSV file: {csv_file}")
    functions = read_csv_data(csv_file)
    print(f"Found {len(functions)} functions")
    print()
    
    # Resolve dependency IDs to function names
    print("Resolving dependencies...")
    resolve_dependencies(functions)
    print()
    
    # Replace team UUIDs with team names
    print("Mapping team UUIDs to names...")
    for function in functions:
        team_id = function['team']
        if team_id in team_mapping:
            team_name = team_mapping[team_id]
            print(f"  ✓ {team_id} → {team_name}")
            function['team'] = team_name
        else:
            print(f"  ⚠ {team_id} (not found in mapping, keeping UUID)")
    print()
    
    # Process each function and collect YAML data
    print("Processing functions...")
    all_yaml_data = []
    for function in functions:
        # Find child functions
        child_functions = find_child_functions(function['path'], functions)
        
        # Create YAML structure
        yaml_data = create_yaml_structure(function, child_functions)
        all_yaml_data.append(yaml_data)
        
        print(f"  • {function['name']} (owner: {function['team']}, children: {len(child_functions)})")
    
    # Write all data to a single file
    print()
    filepath = write_combined_yaml_file(all_yaml_data, output_dir)
    
    print(f"✓ Successfully created {filepath} with {len(all_yaml_data)} functions")


if __name__ == '__main__':
    main()