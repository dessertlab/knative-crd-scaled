#!/bin/bash

# Exits immediately if a command exits with a non-zero status,
# if an undefined variable is used,
# or if any command in a pipeline fails
set -e
set -u
set -o pipefail

# Default values
REAL_TRAFFIC_TEST_MANIFEST="./real-traffic-test.yaml"
ITERATIONS="1"
TEST_TYPE="Deployment"

# Parse command line flags
while getopts "f:i:t:h" opt; do
    case $opt in
        f) REAL_TRAFFIC_TEST_MANIFEST="$OPTARG" ;;
        i) ITERATIONS="$OPTARG" ;;
        t) TEST_TYPE="$OPTARG" ;;
        h) 
            echo "Usage: $0 [-f <manifest-file>] [-i <iterations>] [-t <test-type>] [-h]"
            echo ""
            echo "Options:"
            echo "  -f <manifest-file>  Path to the manifest file (default: ./real-traffic-test.yaml)"
            echo "  -i <iterations>     Number of test iterations (default: 1)"
            echo "  -t <test-type>      Type of test to run (default: Deployment)"
            echo "  -h                  Show this help message"
            exit 0
            ;;
        \?) 
            echo "Error: Invalid option -$OPTARG" >&2
            echo "Use -h for help" >&2
            exit 1
            ;;
        :)
            echo "Error: Option -$OPTARG requires an argument" >&2
            exit 1
            ;;
    esac
done

# Validate manifest file exists
if [[ ! -f "$REAL_TRAFFIC_TEST_MANIFEST" ]]; then
    echo "Error: Manifest file '$REAL_TRAFFIC_TEST_MANIFEST' not found" >&2
    exit 1
fi

# Validate iterations is a positive number
if ! [[ "$ITERATIONS" =~ ^[0-9]+$ ]] || [[ "$ITERATIONS" -lt 1 ]]; then
    echo "Error: Iterations must be a positive number (got: $ITERATIONS)" >&2
    exit 1
fi

# Validate test type
if [[ "$TEST_TYPE" != "Deployment" && "$TEST_TYPE" != "RTResource" ]]; then
    echo "Error: Test type must be either 'Deployment' or 'RTResource' (got: $TEST_TYPE)" >&2
    exit 1
fi

echo "================================================"
echo "Real Traffic Test - Starting"
echo "================================================"
echo "Manifest file: $REAL_TRAFFIC_TEST_MANIFEST"
echo "Iterations:    $ITERATIONS"
echo "Test Type:     $TEST_TYPE"
echo "================================================"
echo ""

# Ensure interference namespace exists
if ! kubectl get namespace interference &>/dev/null; then
    echo "Creating interference namespace..."
    if ! kubectl create namespace interference; then
        echo "Error: Failed to create interference namespace" >&2
        exit 1
    fi
else
    echo "Namespace interference already exists"
fi
echo ""

# Run test iterations
for i in $(seq 1 "$ITERATIONS"); do
    echo "--- Iteration $i/$ITERATIONS ---"
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Applying test manifest..."
    if ! kubectl apply -f "$REAL_TRAFFIC_TEST_MANIFEST"; then
        echo "Error: Failed to apply manifest" >&2
        exit 1
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for test completion..."
    if ! kubectl wait --for=condition=complete job/real-traffic-test -n default --timeout=1000s; then
        echo "Error: Test job failed or timed out" >&2
        kubectl delete -f "$REAL_TRAFFIC_TEST_MANIFEST" || true
        exit 1
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Test completed! Deleting job..."
    kubectl delete -f "$REAL_TRAFFIC_TEST_MANIFEST"

    # Cleanup with retry logic (max 3 attempts)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting cleanup process..."
    CLEANUP_SUCCESS=false
    for attempt in 1 2 3; do
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleaning up resources (attempt $attempt/3)..."
        
        # Delete resources based on test type
        if [[ "$TEST_TYPE" == "RTResource" ]]; then
            kubectl delete --all rtresources -n default --ignore-not-found=true
            kubectl delete --all rtresources -n interference --ignore-not-found=true
        elif [[ "$TEST_TYPE" == "Deployment" ]]; then
            kubectl delete deployment -n default -l "app=perftest" --ignore-not-found=true
            kubectl delete deployment -n interference -l "app=perftest" --ignore-not-found=true
        fi

        # Wait a moment for resources to be deleted
        sleep 5

        # Verify cleanup in interference namespace
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Verifying cleanup in interference namespace..."
        REMAINING_PODS_INTERFERENCE=$(kubectl get pods -n interference --no-headers 2>/dev/null | wc -l)

        if [[ "$REMAINING_PODS_INTERFERENCE" -ne 0 ]]; then
            echo "Warning: Found $REMAINING_PODS_INTERFERENCE pod(s) still running in interference namespace" >&2
            kubectl get pods -n interference
        fi
        
        if [[ "$TEST_TYPE" == "RTResource" ]]; then
            REMAINING_RESOURCES_INTERFERENCE=$(kubectl get rtresources -n interference --no-headers 2>/dev/null | wc -l)
            
            if [[ "$REMAINING_RESOURCES_INTERFERENCE" -ne 0 ]]; then
                echo "Warning: Found $REMAINING_RESOURCES_INTERFERENCE rtresource(s) still present in interference namespace" >&2
                kubectl get rtresources -n interference
            fi
        elif [[ "$TEST_TYPE" == "Deployment" ]]; then
            REMAINING_RESOURCES_INTERFERENCE=$(kubectl get deployment -n interference --no-headers 2>/dev/null | grep "^perftest" | wc -l)
            
            if [[ "$REMAINING_RESOURCES_INTERFERENCE" -ne 0 ]]; then
                echo "Warning: Found $REMAINING_RESOURCES_INTERFERENCE deployment(s) still present in interference namespace" >&2
                kubectl get deployment -n interference | grep "^perftest\|^NAME"
            fi
        fi

        # Verify cleanup in default namespace based on test type
        if [[ "$TEST_TYPE" == "RTResource" ]]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Verifying cleanup in default namespace (perftest RTResources)..."
            REMAINING_PODS_DEFAULT=$(kubectl get pods -n default --no-headers 2>/dev/null | grep "^perftest" | wc -l)
            REMAINING_RESOURCES_DEFAULT=$(kubectl get rtresources -n default --no-headers 2>/dev/null | grep "^perftest" | wc -l)
            
            if [[ "$REMAINING_PODS_DEFAULT" -ne 0 ]]; then
                echo "Warning: Found $REMAINING_PODS_DEFAULT perftest pod(s) still running in default namespace" >&2
                kubectl get pods -n default | grep "^perftest\|^NAME"
            fi
            
            if [[ "$REMAINING_RESOURCES_DEFAULT" -ne 0 ]]; then
                echo "Warning: Found $REMAINING_RESOURCES_DEFAULT perftest rtresource(s) still present in default namespace" >&2
                kubectl get rtresources -n default | grep "^perftest\|^NAME"
            fi
        elif [[ "$TEST_TYPE" == "Deployment" ]]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Verifying cleanup in default namespace (perftest Deployments)..."
            REMAINING_PODS_DEFAULT=$(kubectl get pods -n default --no-headers 2>/dev/null | grep "^perftest" | wc -l)
            REMAINING_RESOURCES_DEFAULT=$(kubectl get deployment -n default --no-headers 2>/dev/null | grep "^perftest" | wc -l)
            
            if [[ "$REMAINING_PODS_DEFAULT" -ne 0 ]]; then
                echo "Warning: Found $REMAINING_PODS_DEFAULT perftest pod(s) still running in default namespace" >&2
                kubectl get pods -n default | grep "^perftest\|^NAME"
            fi
            
            if [[ "$REMAINING_RESOURCES_DEFAULT" -ne 0 ]]; then
                echo "Warning: Found $REMAINING_RESOURCES_DEFAULT perftest deployment(s) still present in default namespace" >&2
                kubectl get deployment -n default | grep "^perftest\|^NAME"
            fi
        fi
        
        # Handle edge case: resources deleted but pods still present
        if [[ "$REMAINING_RESOURCES_INTERFERENCE" -eq 0 ]] && [[ "$REMAINING_PODS_INTERFERENCE" -ne 0 ]]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Resources deleted but pods remain in interference namespace, force deleting pods..."
            kubectl delete pods --all -n interference --force --grace-period=0 2>/dev/null || true
            sleep 5
        fi
        
        if [[ "$REMAINING_RESOURCES_DEFAULT" -eq 0 ]] && [[ "$REMAINING_PODS_DEFAULT" -ne 0 ]]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Resources deleted but perftest pods remain in default namespace, force deleting pods..."
            kubectl get pods -n default --no-headers 2>/dev/null | grep "^perftest" | awk '{print $1}' | xargs -r kubectl delete pod -n default --force --grace-period=0 2>/dev/null || true
            sleep 5
        fi

        # Re-check remaining pods in both namespaces
        REMAINING_PODS_INTERFERENCE=$(kubectl get pods -n interference --no-headers 2>/dev/null | wc -l)
        REMAINING_PODS_DEFAULT=$(kubectl get pods -n default --no-headers 2>/dev/null | grep "^perftest" | wc -l)

        # Check if cleanup was successful
        if [[ "$REMAINING_PODS_INTERFERENCE" -eq 0 ]] && [[ "$REMAINING_RESOURCES_INTERFERENCE" -eq 0 ]] && \
           [[ "$REMAINING_PODS_DEFAULT" -eq 0 ]] && [[ "$REMAINING_RESOURCES_DEFAULT" -eq 0 ]]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleanup successful"
            CLEANUP_SUCCESS=true
            break
        else
            if [[ $attempt -lt 3 ]]; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cleanup incomplete, retrying..."
                sleep 5
            fi
        fi
    done

    if [[ "$CLEANUP_SUCCESS" == false ]]; then
        echo "Error: Failed to clean up namespaces after 3 attempts" >&2
        exit 1
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iteration $i/$ITERATIONS completed!"
    echo ""
done

echo "================================================"
echo "All test iterations completed successfully!"
echo "================================================"
