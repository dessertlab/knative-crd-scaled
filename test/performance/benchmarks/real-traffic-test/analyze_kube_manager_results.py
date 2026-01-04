import os
import sys
import csv
import re
import json


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
        service['pods_created'] = service_data.get('pod_created_mean', '')
        service['pods_started'] = service_data.get('pod_started_mean', '')
    
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
        
        # Set criticality level to NONE
        service_data['criticality_level'] = 'NONE'
        
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
    # Key: deployment name, Value: detailed tracking info
    scale_tracking = {}
    
    # Build mapping from service name to expected deployment name
    # Format: perftest-X -> perftest-X-00001-deployment
    for service in services:
        service_name = service['service_name']
        # Deployment name follows pattern: {service_name}-00001-deployment
        deployment_name = f"{service_name}-00001-deployment"
        scale_tracking[deployment_name] = {
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
            'starts_processing_mean': None,
            # Array of pod_created events with timestamps
            # and the total average of "pod_created" events timings
            'pod_created_events': [],
            'pod_created_mean': None,
            # Array of pod_started events with timestamps
            # and the total average of "pod_started" events timings
            'pod_started_events': [],
            'pod_started_mean': None
        }
    
    print(f"  Analyzing {len(audit_data)} audit log entries...")
    
    # First pass: find the timestamp of the first scale-up event across ALL services
    first_scale_up_timestamp = None
    
    for entry in audit_data:
        log = entry.get('log', {})
        
        if is_scale_up_event(log):
            object_ref = log.get('objectRef', {})
            deployment_name = object_ref.get('name', '')
            
            if deployment_name in scale_tracking:
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

            # Extract deployment name
            object_ref = log.get('objectRef', {})
            deployment_name = object_ref.get('name', '')
            
            if deployment_name not in scale_tracking:
                continue
            
            # Extract new replica count from requestObject
            request_object = log.get('requestObject', [])
            new_replicas = extract_replica_value(request_object)
            
            if new_replicas is None:
                continue
            
            # Update scale tracking
            tracking = scale_tracking[deployment_name]
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
                    'observed_scale': 0,
                    'observed_startup': 0,
                    'used_for_starts_processing': False,
                    'used_for_pods_created': False,
                    'used_for_pods_started': False
                })
                print(f"  Scale-up detected for {tracking['service_name']}: {old_scale} -> {new_replicas} (+{new_replicas - old_scale}) (total: {tracking['scale_up_number']})")
            
            continue
        
        # Check if this is a pod creation event
        if is_pod_created_event(log):
            # Extract deployment_name from requestObject labels
            request_object = log.get('requestObject', {})
            metadata = request_object.get('metadata', {})
            labels = metadata.get('labels', {})
            deployment_name = labels.get('app', '') + '-deployment'
            
            if deployment_name not in scale_tracking:
                continue
            
            tracking = scale_tracking[deployment_name]

            # Find the first unused scale-up event for pods_created
            matching_scale_up = None
            for scale_up_event in tracking['scale_up_events']:
                if not scale_up_event['used_for_pods_created']:
                    matching_scale_up = scale_up_event
                    break
            
            if matching_scale_up is None or matching_scale_up['observed_scale'] >= matching_scale_up['scaled_by']:
                print(f"  Skipping pod creation for {tracking['service_name']}: no unused scale-up found")
                continue
            
            # If this is the first pod for this scale-up, record starts_processing event
            if matching_scale_up['observed_scale'] == 0:
                # Mark this scale-up as used for starts_processing
                matching_scale_up['used_for_starts_processing'] = True

                timestamp = int(entry.get('timestamp', '0'))
                tracking['starts_processing_events'].append({'timestamp': timestamp})
                print(f"  Starts-processing detected for {tracking['service_name']}")
            
            # Increment observed_scale
            matching_scale_up['observed_scale'] += 1
            print(f"  Pod created for {tracking['service_name']}: observed_scale={matching_scale_up['observed_scale']}/{matching_scale_up['scaled_by']}")
            
            # Check if all pods for this scale-up have been created
            if matching_scale_up['observed_scale'] == matching_scale_up['scaled_by']:
                matching_scale_up['used_for_pods_created'] = True
                timestamp = int(entry.get('timestamp', '0'))
                tracking['pod_created_events'].append({'timestamp': timestamp})
                print(f"  All pods created for {tracking['service_name']} scale-up (replicas: {matching_scale_up['replicas']})")
            
            continue
        
        # Check if this is a pod started event
        if is_pod_started_event(log):
            # Extract deployment_name from responseObject metadata labels
            response_object = log.get('responseObject', {})
            metadata = response_object.get('metadata', {})
            labels = metadata.get('labels', {})
            deployment_name = labels.get('app', '') + '-deployment'
            
            if deployment_name not in scale_tracking:
                continue
            
            tracking = scale_tracking[deployment_name]
            
            # Find the first unused scale-up event for pods_started
            matching_scale_up = None
            for scale_up_event in tracking['scale_up_events']:
                if not scale_up_event['used_for_pods_started']:
                    matching_scale_up = scale_up_event
                    break
            
            if matching_scale_up is None or matching_scale_up['observed_startup'] >= matching_scale_up['scaled_by']:
                print(f"  Skipping pod startup for {tracking['service_name']}: no unused scale-up found")
                continue
            
            # Increment observed_startup
            matching_scale_up['observed_startup'] += 1
            print(f"  Pod started for {tracking['service_name']}: observed_startup={matching_scale_up['observed_startup']}/{matching_scale_up['scaled_by']}")
            
            # Check if all pods for this scale-up have been started
            if matching_scale_up['observed_startup'] == matching_scale_up['scaled_by']:
                matching_scale_up['used_for_pods_started'] = True
                timestamp = int(entry.get('timestamp', '0'))
                tracking['pod_started_events'].append({'timestamp': timestamp})
                print(f"  All pods started for {tracking['service_name']} scale-up (replicas: {matching_scale_up['replicas']})")
            
            continue
    
    # Calculate timing metrics for each service
    for deployment_name, tracking in scale_tracking.items():
        calculate_timing_mean(tracking, 'starts_processing_events', 'starts_processing_mean', 'starts_processing')
        calculate_timing_mean(tracking, 'pod_created_events', 'pod_created_mean', 'pod_created')
        calculate_timing_mean(tracking, 'pod_started_events', 'pod_started_mean', 'pod_started')
    
    # Build result dict: service_name -> service_data
    result = {}
    for deployment_name, tracking in scale_tracking.items():
        service_name = tracking['service_name']
        result[service_name] = {
            'scale_up_number': tracking['scale_up_number'],
            'starts_processing_mean': tracking['starts_processing_mean'],
            'pod_created_mean': tracking['pod_created_mean'],
            'pod_started_mean': tracking['pod_started_mean']
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
    if object_ref.get('resource') != 'deployments':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiGroup') != 'apps':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    
    # Check response status
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    return True


def is_pod_created_event(log):
    """
    Check if a log entry represents a pod creation event.
    """
    # Check verb
    if log.get('verb') != 'create':
        return False
    
    # Check user
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:kube-system:replicaset-controller':
        return False
    
    # Check objectRef
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'pods':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    
    # Check response status
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 201:
        return False
    
    return True


def is_pod_started_event(log):
    """
    Check if a log entry represents a pod started event (kubelet patch).
    """
    # Check verb
    if log.get('verb') != 'patch':
        return False
    
    # Check userAgent (kubelet)
    user_agent = log.get('userAgent', '')
    if not user_agent.startswith('kubelet/'):
        return False
    
    # Check objectRef
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'pods':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    if object_ref.get('subresource') != 'status':
        return False
    
    # Check response status
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    # Check responseObject for Running phase and all conditions True
    response_object = log.get('responseObject', {})
    status = response_object.get('status', {})
    
    if status.get('phase') != 'Running':
        return False
    
    conditions = status.get('conditions', [])
    required_conditions = ['PodReadyToStartContainers', 'Initialized', 'Ready', 'ContainersReady', 'PodScheduled']
    
    conditions_status = {}
    for condition in conditions:
        cond_type = condition.get('type')
        if cond_type in required_conditions:
            conditions_status[cond_type] = condition.get('status')
    
    # Verify all required conditions are True
    for req_cond in required_conditions:
        if conditions_status.get(req_cond) != 'True':
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


def calculate_timing_mean(tracking, events_key, mean_key, event_label):
    """
    Calculate the mean time from scale-up to a specific event type.
    Generic function used for starts_processing, pod_created, and pod_started.
    
    Args:
        tracking: The tracking dictionary for a service
        events_key: Key for the events array (e.g., 'starts_processing_events')
        mean_key: Key for the mean result (e.g., 'starts_processing_mean')
        event_label: Human-readable label for logging (e.g., 'starts_processing')
    """
    scale_up_events = tracking['scale_up_events']
    events = tracking[events_key]
    
    # Check if we have events
    if not scale_up_events or not events:
        tracking[mean_key] = None
        return
    
    if len(scale_up_events) > len(events):
        print(f"  Warning: {tracking['service_name']} has {len(scale_up_events)} scale-ups but {len(events)} {event_label} events")
        tracking[mean_key] = None
        return
    
    # Calculate time differences
    time_diffs = []

    i = 0
    j = 0
    while i < len(scale_up_events) and j < len(events):
        scale_up_ts = scale_up_events[i]['timestamp']
        event_ts = events[j]['timestamp']
        
        if event_ts >= scale_up_ts:
            # Calculate time difference in milliseconds
            time_diff_ns = event_ts - scale_up_ts
            time_diff_ms = time_diff_ns / 1_000_000  # Convert nanoseconds to milliseconds
            time_diffs.append(time_diff_ms)
            i += 1
            j += 1
        else:
            j += 1  # Skip this event (it's before current scale-up)
    
    if not time_diffs:
        print(f"  Warning: {tracking['service_name']} - No valid {event_label} events found after scale-ups")
        tracking[mean_key] = None
        return
    
    if i < len(scale_up_events):
        print(f"  Warning: {tracking['service_name']} - Only matched {len(time_diffs)}/{len(scale_up_events)} scale-ups")
    
    # Calculate mean
    mean_time = sum(time_diffs) / len(time_diffs)
    tracking[mean_key] = f"{mean_time:.2f}ms"
    print(f"  Mean {event_label} time for {tracking['service_name']}: {mean_time:.2f}ms (from {len(time_diffs)} scale-ups)")


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
