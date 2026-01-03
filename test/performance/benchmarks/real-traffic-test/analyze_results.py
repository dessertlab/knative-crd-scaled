import os
import sys
import csv
import re
import json
from pathlib import Path


def process_directory(dir_path):
    """
    Process a single directory containing vegeta_metrics.txt and audit_logs.json
    """
    dir_name = os.path.basename(dir_path)
    csv_output_path = os.path.join(dir_path, f"{dir_name}.csv")
    
    # Skip if CSV already exists
    if os.path.exists(csv_output_path):
        print(f"Skipping {dir_path}: CSV already exists")
        return
    
    vegeta_file = os.path.join(dir_path, "vegeta_metrics.txt")
    audit_file = os.path.join(dir_path, "audit_logs.json")
    
    # Check if required files exist
    if not os.path.exists(vegeta_file):
        print(f"Warning: {vegeta_file} not found, skipping directory")
        return
    
    if not os.path.exists(audit_file):
        print(f"Warning: {audit_file} not found, skipping directory")
        return
    
    print(f"Processing {dir_path}...")
    
    # Parse vegeta metrics
    services = parse_vegeta_metrics(vegeta_file)
    
    if not services:
        print(f"Warning: No services found in {vegeta_file}")
        return
    
    # Parse audit logs and count scale-ups
    scale_up_counts = parse_audit_logs(audit_file, services)
    
    # Merge scale-up counts and timing data into services
    for service in services:
        service_name = service['service_name']
        service_data = scale_up_counts.get(service_name, {})
        service['scale_up_number'] = service_data.get('scale_up_number', 0)
        service['starts_processing'] = service_data.get('starts_processing_mean', '')
        service['pods_created'] = ''  # To be implemented
        service['pods_started'] = ''  # To be implemented
    
    # Write CSV
    with open(csv_output_path, 'w', newline='') as csvfile:
        fieldnames = ['service_name', 'criticality_level', 'mean_latency', 'scale_up_number', 
                      'starts_processing', 'pods_created', 'pods_started']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for service in services:
            writer.writerow(service)
    
    print(f"Created {csv_output_path} with {len(services)} services")


def parse_vegeta_metrics(file_path):
    """
    Parse vegeta_metrics.txt and extract service data.
    Returns a list of dicts with: service_name, criticality_level, mean_latency
    """
    services = []
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Split by service sections (each starts with "# Service:")
    service_sections = re.split(r'# Service:', content)[1:]  # Skip first empty part
    
    for section in service_sections:
        service_data = {}
        
        # Extract service name (first line of the section)
        service_match = re.search(r'^(.+?)\n', section)
        if service_match:
            service_data['service_name'] = service_match.group(1).strip()
        
        # Extract criticality level
        criticality_match = re.search(r'Criticality Level:\s*(\d+)', section)
        if criticality_match:
            service_data['criticality_level'] = int(criticality_match.group(1))
        
        # Extract mean latency from Latencies line
        # Format: Latencies [min, mean, 50, 90, 95, 99, max]  5.91ms, 764.926ms, ...
        latency_match = re.search(r'Latencies\s+\[.*?\]\s+[\d.]+\w+,\s+([\d.]+\w+)', section)
        if latency_match:
            service_data['mean_latency'] = latency_match.group(1)
        
        if service_data:
            services.append(service_data)
    
    return services


def parse_audit_logs(file_path, services):
    """
    Parse audit_logs.json and count scale-up events for each service.
    Returns a dict mapping service_name to service_data with metrics.
    """
    # Load audit logs
    with open(file_path, 'r') as f:
        audit_data = json.load(f)
    
    # Sort logs by timestamp
    audit_data.sort(key=lambda x: int(x.get('timestamp', '0')))
    
    # Initialize tracking structure for each service
    # Key: rtresource name, Value: detailed tracking info
    scale_tracking = {}
    
    # Build mapping from service name to expected rtresource name
    # Format: perftest-X -> perftest-X-00001-rtresource
    for service in services:
        service_name = service['service_name']
        # RTResource name follows pattern: {service_name}-00001-rtresource
        rtresource_name = f"{service_name}-00001-rtresource"
        scale_tracking[rtresource_name] = {
            'service_name': service_name,
            # Array of scale-up events with timestamps and usage flags
            # Example:
            #   1st scale up event {
            #       'timestamp': 1234567890,
            #       'replicas': 3,
            #       'scaled_by': 2,
            #       'used_for_starts_processing': False,
            #       'used_for_pods_created': False,
            #       'used_for_pods_started': False
            #   }
            'scale_up_events': [],
            'current_scale': 0,
            'scale_up_number': 0,
            # Array of starts_processing events with timestamps
            # and the total average of "starts_processing" events timings
            'starts_processing_events': [],
            'starts_processing_mean': None
        }
    
    print(f"  Analyzing {len(audit_data)} audit log entries...")
    
    # First pass: find the timestamp of the first scale-up event across ALL services
    first_scale_up_timestamp = None
    
    for entry in audit_data:
        log = entry.get('log', {})
        
        if is_scale_up_event(log):
            object_ref = log.get('objectRef', {})
            rtresource_name = object_ref.get('name', '')
            
            if rtresource_name in scale_tracking:
                request_object = log.get('requestObject', [])
                new_replicas = extract_replica_value(request_object)
                
                if new_replicas is not None and new_replicas > 0:
                    first_scale_up_timestamp = int(entry.get('timestamp', '0'))
                    print(f"  First scale-up found at timestamp {first_scale_up_timestamp}")
                    break
    
    if first_scale_up_timestamp is None:
        print(f"  Warning: No scale-up events found in logs")
        return {}
    
    # Filter audit_data to only include logs after the first scale-up
    audit_data = [entry for entry in audit_data if int(entry.get('timestamp', '0')) >= first_scale_up_timestamp]
    print(f"  After filtering: {len(audit_data)} audit log entries remain")
    
    # Process each log entry
    for entry in audit_data:
        log = entry.get('log', {})
        
        # Check if this is a scale-up event
        if is_scale_up_event(log):

            # Extract rtresource name
            object_ref = log.get('objectRef', {})
            rtresource_name = object_ref.get('name', '')
            
            if rtresource_name not in scale_tracking:
                continue
            
            # Extract new replica count from requestObject
            request_object = log.get('requestObject', [])
            new_replicas = extract_replica_value(request_object)
            
            if new_replicas is None:
                continue
            
            # Update scale tracking
            tracking = scale_tracking[rtresource_name]
            if new_replicas > tracking['current_scale']:
                tracking['scale_up_number'] += 1
                old_scale = tracking['current_scale']
                tracking['current_scale'] = new_replicas
                # Store scale-up event with timestamp and replica count
                timestamp = int(entry.get('timestamp', '0'))
                tracking['scale_up_events'].append({
                    'timestamp': timestamp,
                    'replicas': new_replicas,
                    'scaled_by': new_replicas - old_scale,
                    'used_for_starts_processing': False,
                    'used_for_pods_created': False,
                    'used_for_pods_started': False
                })
                print(f"  Scale-up detected for {tracking['service_name']}: {old_scale} -> {new_replicas} (+{new_replicas - old_scale}) (total: {tracking['scale_up_number']})")
            
            continue

        # Check if this is a starts_processing event
        if is_starts_processing_event(log):
            object_ref = log.get('objectRef', {})
            rtresource_name = object_ref.get('name', '')
            
            if rtresource_name not in scale_tracking:
                continue
            
            tracking = scale_tracking[rtresource_name]
            
            # Extract desiredReplicas from responseObject status
            response_object = log.get('responseObject', {})
            status = response_object.get('status', {})
            desired_replicas = status.get('desiredReplicas')
            
            # Find the first unused scale-up event that matches desiredReplicas
            matching_scale_up = None
            for scale_up_event in tracking['scale_up_events']:
                if not scale_up_event['used_for_starts_processing'] and scale_up_event['replicas'] == desired_replicas:
                    matching_scale_up = scale_up_event
                    break
            
            if matching_scale_up is None:
                print(f"  Skipping starts-processing for {tracking['service_name']}: no matching scale-up found with replicas={desired_replicas}")
                continue
            
            # Mark this scale-up as used
            matching_scale_up['used_for_starts_processing'] = True
            
            timestamp = int(entry.get('timestamp', '0'))
            tracking['starts_processing_events'].append({'timestamp': timestamp})
            print(f"  Starts-processing detected for {tracking['service_name']} (desiredReplicas: {desired_replicas})")

            continue
    
    # Calculate "starts_processinfg" avarages for each service
    for rtresource_name, tracking in scale_tracking.items():
        calculate_starts_processing_mean(tracking)
    
    # Build result dict: service_name -> service_data
    result = {}
    for rtresource_name, tracking in scale_tracking.items():
        service_name = tracking['service_name']
        result[service_name] = {
            'scale_up_number': tracking['scale_up_number'],
            'starts_processing_mean': tracking['starts_processing_mean']
        }
    
    return result


def is_scale_up_event(log):
    """
    Check if a log entry represents a potential scale-up event.
    """
    # Check verb
    if log.get('verb') != 'patch':
        return False
    
    # Check user
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:knative-serving:controller':
        return False
    
    # Check userAgent
    user_agent = log.get('userAgent', '')
    if not user_agent.startswith('autoscaler/'):
        return False
    
    # Check objectRef
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'rtresources':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiGroup') != 'rtgroup.critical.com':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    
    # Check response status
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    return True


def extract_replica_value(request_object):
    """
    Extract the replica value from requestObject.
    requestObject is a JSON patch array.
    """
    if not isinstance(request_object, list):
        return None
    
    for operation in request_object:
        if not isinstance(operation, dict):
            continue
        
        if operation.get('op') == 'replace' and operation.get('path') == '/spec/replicas':
            value = operation.get('value')
            if isinstance(value, int):
                return value
    
    return None


def is_starts_processing_event(log):
    """
    Check if a log entry represents a starts_processing event.
    """
    # Check verb
    if log.get('verb') != 'update':
        return False
    
    # Check user
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:realtime:preempt-k8s':
        return False
    
    # Check objectRef
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'rtresources':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiGroup') != 'rtgroup.critical.com':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    if object_ref.get('subresource') != 'status':
        return False
    
    # Check response status
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    # Check responseObject conditions
    response_object = log.get('responseObject', {})
    status = response_object.get('status', {})
    conditions = status.get('conditions', [])
    
    progressing_true = False
    ready_false = False
    progressing_transition_time = None
    ready_transition_time = None
    
    for condition in conditions:
        if condition.get('type') == 'Progressing' and condition.get('status') == 'True':
            progressing_true = True
            progressing_transition_time = condition.get('lastTransitionTime')
        if condition.get('type') == 'Ready' and condition.get('status') == 'False':
            ready_false = True
            ready_transition_time = condition.get('lastTransitionTime')
    
    # Verify both conditions are met and their lastTransitionTime is identical
    if not (progressing_true and ready_false):
        return False
    
    if progressing_transition_time is None or ready_transition_time is None:
        return False
    
    if progressing_transition_time != ready_transition_time:
        return False
    
    return True


def calculate_starts_processing_mean(tracking):
    """
    Calculate the mean time from scale-up to starts_processing.
    Updates tracking['starts_processing_mean'].
    """
    scale_up_events = tracking['scale_up_events']
    starts_processing_events = tracking['starts_processing_events']
    
    # Check if we have events and if arrays have same length
    if not scale_up_events or not starts_processing_events:
        tracking['starts_processing_mean'] = None
        return
    
    if len(scale_up_events) > len(starts_processing_events):
        print(f"  Warning: {tracking['service_name']} has {len(scale_up_events)} scale-ups but {len(starts_processing_events)} starts_processing events")
        tracking['starts_processing_mean'] = None
        return
    
    # Calculate time differences
    time_diffs = []

    i = 0
    j = 0
    while i < len(scale_up_events) and j < len(starts_processing_events):
        scale_up_ts = scale_up_events[i]['timestamp']
        sp_ts = starts_processing_events[j]['timestamp']
        
        if sp_ts >= scale_up_ts:
            # Calculate time difference in milliseconds
            time_diff_ns = sp_ts - scale_up_ts
            time_diff_ms = time_diff_ns / 1_000_000  # Convert nanoseconds to milliseconds
            time_diffs.append(time_diff_ms)
            i += 1
            j += 1
        else:
            j += 1  # Skip this starts_processing event (it's before current scale-up)
    
    if not time_diffs:
        print(f"  Warning: {tracking['service_name']} - No valid starts_processing events found after scale-ups")
        tracking['starts_processing_mean'] = None
        return
    
    if i < len(scale_up_events):
        print(f"  Warning: {tracking['service_name']} - Only matched {len(time_diffs)}/{len(scale_up_events)} scale-ups")
    
    # Calculate mean
    mean_time = sum(time_diffs) / len(time_diffs)
    tracking['starts_processing_mean'] = f"{mean_time:.2f}ms"
    print(f"  Mean starts_processing time for {tracking['service_name']}: {mean_time:.2f}ms (from {len(time_diffs)} scale-ups)")


def main():
    if len(sys.argv) != 2:
        print("Usage: python analyze_results.py <path_to_results_directory>")
        sys.exit(1)
    
    root_path = sys.argv[1]
    
    if not os.path.isdir(root_path):
        print(f"Error: {root_path} is not a valid directory")
        sys.exit(1)
    
    print(f"Scanning directories in {root_path}...")
    
    # Find all subdirectories
    processed_count = 0
    for entry in os.listdir(root_path):
        subdir_path = os.path.join(root_path, entry)
        
        if os.path.isdir(subdir_path):
            process_directory(subdir_path)
            processed_count += 1
    
    print(f"\nProcessed {processed_count} directories")


if __name__ == "__main__":
    main()
