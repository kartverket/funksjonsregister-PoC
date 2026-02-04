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
    python3 csv_to_yaml.py funkreg.csv output_folder team_names.csv

"""

import csv
import os
import sys
import yaml
from pathlib import Path


def sanitize_for_owner(name):
    """
    Sanitize name for use in owner field.
    Rules:
    - Replace whitespace with underscore
    - Remove æøå (and their uppercase versions)
    - Keep : and / (for Backstage entity refs like group:default/teamname)
    - Remove other special characters (keep only alphanumeric, hyphens, underscores, periods, colons, slashes)
    - Convert to lowercase
    
    Example: "Group: Default/Team Name!" -> "group:_default/team_name"
    """
    # Replace whitespace with underscore
    sanitized = name.replace(' ', '_')
    
    # Remove æøå characters (both lowercase and uppercase)
    chars_to_remove = 'æøåÆØÅ'
    for char in chars_to_remove:
        sanitized = sanitized.replace(char, '')
    
    # Keep only alphanumeric characters, hyphens, underscores, periods, colons, and slashes
    sanitized = ''.join(c for c in sanitized if c.isalnum() or c in '-_.:/')
    
    # Convert to lowercase
    sanitized = sanitized.lower()
    
    return sanitized


def sanitize_for_metadata(name):
    """
    Sanitize name for use in metadata.name and owner field.
    Rules:
    - Replace whitespace with underscore
    - Remove æøå (and their uppercase versions)
    - Remove special characters (keep only alphanumeric, hyphens, underscores, periods)
    - Convert to lowercase
    
    Example: "Testø - team-lead!" -> "test_-_team-lead"
    """
    # Replace whitespace with underscore
    sanitized = name.replace(' ', '_')
    
    # Remove æøå characters (both lowercase and uppercase)
    chars_to_remove = 'æøåÆØÅ'
    for char in chars_to_remove:
        sanitized = sanitized.replace(char, '')
    
    # Keep only alphanumeric characters, hyphens, underscores, and periods
    sanitized = ''.join(c for c in sanitized if c.isalnum() or c in '-_.')
    
    # Convert to lowercase
    sanitized = sanitized.lower()
    
    sanitized = sanitized.strip('.-_\\')
    
    return sanitized


def load_team_names(team_csv_file):
    """Load team UUID to name mapping from CSV."""
    team_mapping = {}
    
    with open(team_csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            team_id = row['id']
            team_name = row['displayName']
            
            # Remove AAD - TF prefixes if present
            prefixes = [
                "AAD - TF - TEAM - ",
                "AAD - TF - BUSINESS UNIT - ",
                "AAD - TF - PRODUCT AREA - ",
                "AAD - TF - ROLE - "
            ]
            
            for prefix in prefixes:
                if team_name.startswith(prefix):
                    team_name = team_name[len(prefix):]
                    break
            
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
        func_name = sanitize_for_metadata(func['name'])
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
    
    chars_to_remove = 'æøåÆØÅ'
    for char in chars_to_remove:
        name = name.replace(char, '')
    
    # Replace spaces and special characters with hyphens
    filename = name.lower().replace(' ', '-')
    # Remove any characters that aren't alphanumeric or hyphens
    filename = ''.join(c for c in filename if c.isalnum() or c == '-')
    # Remove consecutive hyphens
    filename = '-'.join(filter(None, filename.split('-')))
    return filename


def find_parent_function(current_path, all_functions):
    """
    Find the parent function based on path hierarchy.
    A parent has a path that is exactly one level up.
    
    Example: 
    - Child: "1.4.5" -> Parent: "1.4"
    - Child: "1.4.5.9" -> Parent: "1.4.5"
    - Child: "1.4" -> Parent: "rootfunction" (top-level)
    """
    path_parts = current_path.split('.')
    
    # If only 2 parts (e.g., "1.4"), this is a top-level function
    # Its parent is "rootfunction"
    if len(path_parts) <= 2:
        return "rootfunction"
    
    # Get parent path by removing the last part
    parent_path = '.'.join(path_parts[:-1])
    
    # Find the parent function
    for func in all_functions:
        if func['path'] == parent_path:
            return sanitize_for_metadata(func['name'])
    
    return None


def find_child_functions(current_path, all_functions):
    """
    Find direct child functions based on path hierarchy.
    Used for determining folder structure.
    
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
                children.append(func)
    
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
                'beskrivelse': row.get('beskrivelse', ''),  # Default to empty string if missing
                'kritikalitet': row.get('kritikalitet', ''),
                'dependencies': dependencies
            })
    
    return functions


def create_yaml_structure(function, parent_function):
    """Create the YAML structure for a function."""
    # Get original name for title and metadata.name
    original_name = function['name'].strip()
    
    # Sanitize the name for metadata.name (use original name)
    metadata_name = sanitize_for_metadata(original_name)
    
    team_value = function['team']
    if team_value == "group:default/kartverket" or team_value == "kartverket":
        sanitized_owner = "group:default/statens_kartverk"
    else:
        # Sanitize owner using owner-specific sanitization (keeps : and /)
        sanitized_owner = sanitize_for_owner(team_value)
    
    yaml_data = {
        'apiVersion': 'kartverket.dev/v1alpha1',
        'kind': 'Function',
        'metadata': {
            'name': metadata_name,
            'title': original_name,
            'description': function['beskrivelse'] if function['beskrivelse'] else ''
        },
        'spec': {
            'owner': sanitized_owner,
            'criticality': function['kritikalitet'] if function['kritikalitet'] else '',
            'parentFunction': parent_function,
            'dependsOnFunctions': function['dependencies']
        }
    }
    
    return yaml_data


def write_locations_file(created_files, output_dir):
    """
    Create a locations.yaml file at the root with references to all YAML files.
    """
    # Convert absolute paths to relative paths from output_dir
    relative_paths = []
    for file_path in created_files:
        try:
            rel_path = file_path.relative_to(output_dir)
            relative_paths.append(f"./{rel_path}")
        except ValueError:
            # If we can't make it relative, use the path as-is
            relative_paths.append(str(file_path))
    
    # Sort for consistency
    relative_paths.sort()
    
    # Create the locations.yaml content
    locations_data = {
        'apiVersion': 'backstage.io/v1alpha1',
        'kind': 'Location',
        'metadata': {
            'name': 'Functions'
        },
        'spec': {
            'type': 'url',
            'targets': relative_paths
        }
    }
    
    # Write the locations file, name it catalog-info.yaml
    locations_file = output_dir / 'catalog-info.yaml'
    with open(locations_file, 'w', encoding='utf-8') as f:
        # Add comment at the top
        f.write('# nonk8s\n')
        yaml.dump(locations_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    print(f"  ✓ Created catalog-info.yaml with {len(relative_paths)} targets")
    return locations_file


def write_yaml_files_hierarchically(functions, output_dir):
    """
    Write YAML files in a hierarchical folder structure.
    - Every function gets its own folder
    - Each YAML file contains only one function
    """
    # Create a lookup for quick access
    functions_by_path = {func['path']: func for func in functions}
    
    # Find all top-level functions (paths with exactly 2 parts, e.g., "1.4")
    top_level_functions = [func for func in functions if len(func['path'].split('.')) == 2]
    
    created_files = []
    
    def write_function_recursively(function, parent_dir):
        """Recursively write a function and its descendants."""
        func_name = sanitize_filename(function['name'])
        child_functions_list = find_child_functions(function['path'], functions)
        
        # Every function gets its own folder
        func_folder = parent_dir / func_name
        func_folder.mkdir(parents=True, exist_ok=True)
        
        # Write the function's YAML file inside its folder
        yaml_file = func_folder / f"{func_name}.yaml"
        
        # Find parent function for this function
        parent_function = find_parent_function(function['path'], functions)
        
        # Write this function's YAML
        with open(yaml_file, 'w', encoding='utf-8') as f:
            yaml_data = create_yaml_structure(function, parent_function)
            yaml.dump(yaml_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        created_files.append(yaml_file)
        
        # Recursively process children
        for child_func in child_functions_list:
            # Children go inside this function's folder
            write_function_recursively(child_func, func_folder)
    
    # Process each top-level function
    for top_func in top_level_functions:
        write_function_recursively(top_func, output_dir)
        func_name = sanitize_filename(top_func['name'])
        print(f"  ✓ Created folder structure for {func_name}")
    
    return created_files


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
    
    # Write YAML files organized by hierarchy
    print("Creating YAML files...")
    created_files = write_yaml_files_hierarchically(functions, output_dir)
    
    print()
    print("Creating catalog-info.yaml...")
    locations_file = write_locations_file(created_files, output_dir)
    
    print()
    print(f"✓ Successfully created {len(created_files)} YAML file(s) in {output_dir}")
    print(f"✓ Created {locations_file.name} with all function references")


if __name__ == '__main__':
    main()