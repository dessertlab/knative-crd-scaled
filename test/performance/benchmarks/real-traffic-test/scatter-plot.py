import sys
import os
import json
import re
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


def parse_vegeta_metrics(file_path):
    """
    Parse vegeta_metrics.txt to extract service names.
    Returns a list of service names in order.
    """
    services = []
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Split by service sections (each starts with "# Service:")
    service_sections = re.split(r'# Service:', content)[1:]  # Skip first empty part
    
    for section in service_sections:
        # Extract service name (first line of the section)
        service_match = re.search(r'^(.+?)\n', section)
        if service_match:
            service_name = service_match.group(1).strip()
            services.append(service_name)
    
    return services


def is_scale_up_event_kube(log):
    """Check if a log entry represents a scale-up event for kube-manager."""
    if log.get('verb') != 'patch':
        return False
    
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:knative-serving:controller':
        return False
    
    user_agent = log.get('userAgent', '')
    if not user_agent.startswith('autoscaler/'):
        return False
    
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'deployments':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiGroup') != 'apps':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    return True


def is_scale_up_event_preempt(log):
    """Check if a log entry represents a scale-up event for preempt-k8s."""
    if log.get('verb') != 'patch':
        return False
    
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:knative-serving:controller':
        return False
    
    user_agent = log.get('userAgent', '')
    if not user_agent.startswith('autoscaler/'):
        return False
    
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'rtresources':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiGroup') != 'rtgroup.critical.com':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    return True


def is_starts_processing_event(log):
    """Check if a log entry represents a starts_processing event."""
    if log.get('verb') != 'update':
        return False
    
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:realtime:preempt-k8s':
        return False
    
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
    
    if not (progressing_true and ready_false):
        return False
    
    if not (progressing_true and ready_false):
        return False
    
    if progressing_transition_time != ready_transition_time:
        return False
    
    return True


def is_pod_created_event_kube(log):
    """Check if a log entry represents a pod creation event for kube-manager."""
    if log.get('verb') != 'create':
        return False
    
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:kube-system:replicaset-controller':
        return False
    
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'pods':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 201:
        return False
    
    return True


def is_pod_created_event_preempt(log):
    """Check if a log entry represents a pod creation event for preempt-k8s."""
    if log.get('verb') != 'create':
        return False
    
    user = log.get('user', {})
    if user.get('username') != 'system:serviceaccount:realtime:preempt-k8s':
        return False
    
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'pods':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 201:
        return False
    
    return True


def is_pod_started_event(log):
    """Check if a log entry represents a pod started event."""
    if log.get('verb') != 'patch':
        return False
    
    user_agent = log.get('userAgent', '')
    if not user_agent.startswith('kubelet/'):
        return False
    
    object_ref = log.get('objectRef', {})
    if object_ref.get('resource') != 'pods':
        return False
    if object_ref.get('namespace') != 'default':
        return False
    if object_ref.get('apiVersion') != 'v1':
        return False
    if object_ref.get('subresource') != 'status':
        return False
    
    response_status = log.get('responseStatus', {})
    if response_status.get('code') != 200:
        return False
    
    # Check responseObject for Running phase
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


def parse_audit_logs(file_path, services, mode):
    """
    Parse audit_logs.json and extract all events with timestamps.
    Replicates exactly the logic from analyze_kube_manager_results.py and analyze_preempt_k8s_results.py
    
    Args:
        file_path: Path to audit_logs.json
        services: List of service names
        mode: 'kube' for kube-manager, 'preempt' for preempt-k8s
    
    Returns:
        Dictionary mapping service_name to list of events
        Each event is: {'type': str, 'timestamp': float}
    """
    # Load audit logs
    with open(file_path, 'r') as f:
        audit_data = json.load(f)
    
    # Sort logs by timestamp
    audit_data.sort(key=lambda x: int(x.get('timestamp', '0')))
    
    # Initialize tracking structure for each service
    scale_tracking = {}
    
    if mode == 'kube':
        # Build mapping from deployment name to tracking info
        for service in services:
            deployment_name = f"{service}-00001-deployment"
            scale_tracking[deployment_name] = {
                'service_name': service,
                'scale_up_events': [],
                'current_scale': 0,
                'starts_processing_events': [],
                'pod_created_events': [],
                'pod_started_events': []
            }
    else:  # preempt
        # Build mapping from rtresource name to tracking info
        for service in services:
            rtresource_name = f"{service}-00001-rtresource"
            scale_tracking[rtresource_name] = {
                'service_name': service,
                'scale_up_events': [],
                'current_scale': 0,
                'starts_processing_events': [],
                'pod_created_events': [],
                'pod_started_events': []
            }
    
    print(f"  Analyzing {len(audit_data)} audit log entries...")
    
    # First pass: find the timestamp of the first scale-up event
    first_scale_up_timestamp = None
    
    if mode == 'kube':
        is_scale_up_fn = is_scale_up_event_kube
    else:
        is_scale_up_fn = is_scale_up_event_preempt
    
    for entry in audit_data:
        log = entry.get('log', {})
        
        if is_scale_up_fn(log):
            object_ref = log.get('objectRef', {})
            resource_name = object_ref.get('name', '')
            
            if resource_name in scale_tracking:
                request_object = log.get('requestObject', [])
                new_replicas = extract_replica_value(request_object)
                
                if new_replicas is not None and new_replicas > 0:
                    first_scale_up_timestamp = int(entry.get('timestamp', '0'))
                    print(f"  First scale-up found at timestamp {first_scale_up_timestamp}")
                    break
    
    if first_scale_up_timestamp is None:
        print(f"  Warning: No scale-up events found in logs")
        return {service: [] for service in services}
    
    # Filter audit_data to only include logs after the first scale-up
    audit_data = [entry for entry in audit_data if int(entry.get('timestamp', '0')) >= first_scale_up_timestamp]
    print(f"  After filtering: {len(audit_data)} audit log entries remain")
    
    # Process each log entry - replicate exact behavior from original scripts
    for entry in audit_data:
        log = entry.get('log', {})
        
        # Check if this is a scale-up event
        if mode == 'kube':
            is_scale_up_fn = is_scale_up_event_kube
        else:
            is_scale_up_fn = is_scale_up_event_preempt
        
        if is_scale_up_fn(log):
            object_ref = log.get('objectRef', {})
            resource_name = object_ref.get('name', '')
            
            if resource_name not in scale_tracking:
                continue
            
            request_object = log.get('requestObject', [])
            new_replicas = extract_replica_value(request_object)
            
            if new_replicas is None:
                continue
            
            tracking = scale_tracking[resource_name]
            if new_replicas > tracking['current_scale']:
                old_scale = tracking['current_scale']
                tracking['current_scale'] = new_replicas
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
            continue
        
        # For preempt: Check if this is a starts_processing event
        if mode == 'preempt' and is_starts_processing_event(log):
            object_ref = log.get('objectRef', {})
            rtresource_name = object_ref.get('name', '')
            
            if rtresource_name not in scale_tracking:
                continue
            
            tracking = scale_tracking[rtresource_name]
            
            response_object = log.get('responseObject', {})
            status = response_object.get('status', {})
            desired_replicas = status.get('desiredReplicas')
            
            matching_scale_up = None
            for scale_up_event in tracking['scale_up_events']:
                if not scale_up_event['used_for_starts_processing'] and scale_up_event['replicas'] == desired_replicas:
                    matching_scale_up = scale_up_event
                    break
            
            if matching_scale_up is None:
                continue
            
            matching_scale_up['used_for_starts_processing'] = True
            timestamp = int(entry.get('timestamp', '0'))
            tracking['starts_processing_events'].append({'timestamp': timestamp})
            continue
        
        # Check if this is a pod creation event
        if mode == 'kube':
            is_pod_created_fn = is_pod_created_event_kube
        else:
            is_pod_created_fn = is_pod_created_event_preempt
        
        if is_pod_created_fn(log):
            if mode == 'kube':
                request_object = log.get('requestObject', {})
                metadata = request_object.get('metadata', {})
                labels = metadata.get('labels', {})
                resource_name = labels.get('app', '') + '-deployment'
            else:  # preempt
                request_object = log.get('requestObject', {})
                metadata = request_object.get('metadata', {})
                labels = metadata.get('labels', {})
                resource_name = labels.get('rtresource_name', '')
            
            if resource_name not in scale_tracking:
                continue
            
            tracking = scale_tracking[resource_name]
            
            matching_scale_up = None
            for scale_up_event in tracking['scale_up_events']:
                if not scale_up_event['used_for_pods_created']:
                    matching_scale_up = scale_up_event
                    break
            
            if matching_scale_up is None or matching_scale_up['observed_scale'] >= matching_scale_up['scaled_by']:
                continue
            
            # For kube mode: if this is the first pod, record starts_processing
            if mode == 'kube' and matching_scale_up['observed_scale'] == 0:
                if not matching_scale_up['used_for_starts_processing']:
                    matching_scale_up['used_for_starts_processing'] = True
                    timestamp = int(entry.get('timestamp', '0'))
                    tracking['starts_processing_events'].append({'timestamp': timestamp})
            
            matching_scale_up['observed_scale'] += 1
            
            if matching_scale_up['observed_scale'] == matching_scale_up['scaled_by']:
                matching_scale_up['used_for_pods_created'] = True
                timestamp = int(entry.get('timestamp', '0'))
                tracking['pod_created_events'].append({'timestamp': timestamp})
            
            continue
        
        # Check if this is a pod started event
        if is_pod_started_event(log):
            if mode == 'kube':
                response_object = log.get('responseObject', {})
                metadata = response_object.get('metadata', {})
                labels = metadata.get('labels', {})
                resource_name = labels.get('app', '') + '-deployment'
            else:  # preempt
                response_object = log.get('responseObject', {})
                metadata = response_object.get('metadata', {})
                labels = metadata.get('labels', {})
                resource_name = labels.get('rtresource_name', '')
            
            if resource_name not in scale_tracking:
                continue
            
            tracking = scale_tracking[resource_name]
            
            matching_scale_up = None
            for scale_up_event in tracking['scale_up_events']:
                if not scale_up_event['used_for_pods_started']:
                    matching_scale_up = scale_up_event
                    break
            
            if matching_scale_up is None or matching_scale_up['observed_startup'] >= matching_scale_up['scaled_by']:
                continue
            
            matching_scale_up['observed_startup'] += 1
            
            if matching_scale_up['observed_startup'] == matching_scale_up['scaled_by']:
                matching_scale_up['used_for_pods_started'] = True
                timestamp = int(entry.get('timestamp', '0'))
                tracking['pod_started_events'].append({'timestamp': timestamp})
            
            continue
    
    # Convert tracked events to output format
    service_events = {service: [] for service in services}
    
    for resource_name, tracking in scale_tracking.items():
        service_name = tracking['service_name']
        
        # Add scale-up events
        for scale_up in tracking['scale_up_events']:
            relative_time_ms = (scale_up['timestamp'] - first_scale_up_timestamp) / 1_000_000
            service_events[service_name].append({
                'type': 'scale-up',
                'timestamp': relative_time_ms
            })
        
        # Add starts_processing events
        for event in tracking['starts_processing_events']:
            relative_time_ms = (event['timestamp'] - first_scale_up_timestamp) / 1_000_000
            service_events[service_name].append({
                'type': 'starts_processing',
                'timestamp': relative_time_ms
            })
        
        # Add pod_created events
        for event in tracking['pod_created_events']:
            relative_time_ms = (event['timestamp'] - first_scale_up_timestamp) / 1_000_000
            service_events[service_name].append({
                'type': 'pod_created',
                'timestamp': relative_time_ms
            })
        
        # Add pod_started events
        for event in tracking['pod_started_events']:
            relative_time_ms = (event['timestamp'] - first_scale_up_timestamp) / 1_000_000
            service_events[service_name].append({
                'type': 'pod_started',
                'timestamp': relative_time_ms
            })
    
    # Print summary
    for service_name, events in service_events.items():
        if events:
            event_counts = {}
            for event in events:
                event_type = event['type']
                event_counts[event_type] = event_counts.get(event_type, 0) + 1
            print(f"  {service_name}: {len(events)} events - {event_counts}")
    
    return service_events


def create_scatter_plot(service_events, output_path, mode):
    """
    Create a scatter plot with services on Y-axis and time on X-axis.
    
    Args:
        service_events: Dictionary mapping service_name to list of events
        output_path: Path to save the plot
        mode: 'kube' or 'preempt'
    """
    # Define colors for each event type
    colors = {
        'scale-up': '#3498db',              # Blue
        'starts_processing': '#e74c3c',     # Red
        'pod_created': '#f39c12',           # Orange
        'pod_started': '#2ecc71',           # Green
    }
    
    # Define markers for each event type
    markers = {
        'scale-up': 'D',           # Diamond
        'starts_processing': 's',  # Square
        'pod_created': 'o',        # Circle
        'pod_started': '^'         # Triangle
    }
    
    # Prepare data for plotting
    service_names = list(service_events.keys())
    
    # Create figure with larger size
    fig, ax = plt.subplots(figsize=(16, max(8, len(service_names) * 0.5)))
    
    # Plot events for each service
    for i, service_name in enumerate(service_names):
        events = service_events[service_name]
        
        # Group events by type
        events_by_type = {}
        for event in events:
            event_type = event['type']
            if event_type not in events_by_type:
                events_by_type[event_type] = []
            events_by_type[event_type].append(event['timestamp'])
        
        # Plot each event type
        for event_type, timestamps in events_by_type.items():
            y_values = [i] * len(timestamps)
            ax.scatter(
                timestamps, 
                y_values, 
                c=colors[event_type], 
                marker=markers[event_type],
                s=100,
                alpha=0.7,
                edgecolors='black',
                linewidth=0.5,
                label=event_type if i == 0 else "",
                zorder=3
            )
    
    # Configure axes
    ax.set_xlabel('Time (milliseconds)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Service', fontsize=12, fontweight='bold')
    ax.set_yticks(range(len(service_names)))
    ax.set_yticklabels(service_names, fontsize=9)
    
    # Add horizontal grid lines for each service
    for i in range(len(service_names)):
        ax.axhline(y=i, color='gray', linestyle='--', alpha=0.3, linewidth=0.5, zorder=1)
    
    # Add vertical grid
    ax.grid(True, axis='x', alpha=0.3, linestyle='--', linewidth=0.5, zorder=1)
    
    # Set title
    mode_title = "Kube Manager" if mode == 'kube' else "Preempt-K8s"
    ax.set_title(f'Event Timeline - {mode_title}', fontsize=14, fontweight='bold', pad=20)
    
    # Create legend
    legend_elements = [
        mpatches.Patch(color=colors['scale-up'], label='Scale-up'),
    ]
    if mode == 'preempt':
        legend_elements.append(mpatches.Patch(color=colors['starts_processing'], label='Starts Processing'))
    legend_elements.extend([
        mpatches.Patch(color=colors['pod_created'], label='Pod Created'),
        mpatches.Patch(color=colors['pod_started'], label='Pod Started')
    ])
    
    ax.legend(
        handles=legend_elements,
        loc='upper right',
        fontsize=10,
        framealpha=0.9,
        edgecolor='black'
    )
    
    # Adjust layout
    plt.tight_layout()
    
    # Save plot
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"\nScatter plot saved to: {output_path}")


def main():
    if len(sys.argv) != 3:
        print("Usage: python scatter-plot.py <path_to_directory> <mode>")
        print("Example: python scatter-plot.py ./results/run-1 kube-manager")
        sys.exit(1)
    
    dir_path = sys.argv[1]
    mode = sys.argv[2]  # 'kube-manager' or 'preempt-k8s'
    
    # Normalize mode to 'kube' or 'preempt'
    if mode == 'kube-manager':
        mode = 'kube'
    elif mode == 'preempt-k8s':
        mode = 'preempt'
    
    if not os.path.isdir(dir_path):
        print(f"Error: {dir_path} is not a valid directory")
        sys.exit(1)
    
    # Check for required files
    vegeta_file = os.path.join(dir_path, "vegeta_metrics.txt")
    audit_file = os.path.join(dir_path, "audit_logs.json")
    
    if not os.path.exists(vegeta_file):
        print(f"Error: {vegeta_file} not found")
        sys.exit(1)
    
    if not os.path.exists(audit_file):
        print(f"Error: {audit_file} not found")
        sys.exit(1)
    
    print(f"Processing directory: {dir_path}")
    
    # Parse vegeta metrics to get service names
    services = parse_vegeta_metrics(vegeta_file)
    
    if not services:
        print("Error: No services found in vegeta_metrics.txt")
        sys.exit(1)
    
    print(f"Found {len(services)} services: {', '.join(services)}")
    
    # Parse audit logs and extract events
    service_events = parse_audit_logs(audit_file, services, mode)
    
    # Create scatter plot
    output_path = os.path.join(dir_path, f"scatter-plot.png")
    create_scatter_plot(service_events, output_path, mode)
    
    print("\nDone!")


if __name__ == "__main__":
    main()
