# Real Traffic Test Benchmark

This test is a modified version of the *Real Traffic Test* found in the **Knative** codebase.

## Table of Contents

- [Purpose of the Test](#purpose-of-the-test)
- [Test Configuration](#test-configuration)
- [Prerequisites](#prerequisites)
- [Relevant Notes](#relevant-notes)
- [Results Collection](#results-collection)
- [Test Setup](#test-setup)
- [Run the Test](#run-the-test)
- [Process Results](#process-results)
  - [analyze_preempt_k8s_results.py](#analyze_preempt_k8s_resultspy)
  - [analyze_kube_manager_results.py](#analyze_kube_manager_resultspy)
  - [aggregate_results.py](#aggregate_resultspy)
  - [Important Notes](#important-notes)
  - [Metrics Definition](#metrics-definition)
- [Monitoring Overhead](#monitoring-overhead)
  - [monitoring-overhead.py](#monitoring-overheadpy)
- [Sensitivity Analysis](#sensitivity-analysis)
  - [sensitivity-analysis.py](#sensitivity-analysispy)
  - [sensitivity-analysis-5-threads.py](#sensitivity-analysis-5-threadspy)
  - [scatter-plot.py](#scatter-plotpy)

## Purpose of the Test

This test compares the performance of the **kube-Manger** controller for **Deployments** and **ReplicaSets** against the **PREEMPT-FaaS** custom controller for **RTResources** (the resource equivalent of K8s Deployments for real-time applications). We might also refer to this controller as **PREEMPT-K8s** or **preempt-k8s** since it is the initial name of the PREEMPT-FaaS project.

We deploy a given number of services managed by Knative with a concurrency level set to `5`. If the test is `critical`, Knative relies on **RTResources** setting the proper priorities to each service to handle. otherwise, it uses standard **Deployments**. The test starts by deploying these services and waiting for them to **scale to zero** and to scrape out old logs.

Using **Vegeta**, the test generates a given number of requests-per-second equally distributed to each service in **round-robin** fashion. This triggers a scale-up of each service according to percieved load and the Knative **autoscaler**'s calculations. The tests lasts 1 minute, even though the scale-up stabilizes after a few seconds.

At the same time, other parallel routines generate an interfering load on the control plane by creating or deleting other **RTResources**/**Deployments**. The interfering pods are assigned to a bucket node, not used by the Knative services' pods to exclude their interference on the **nodes** and relative **Kubelets**. We also use a separate namespace to exclude these requests from the collected pods (the main Knative services are deployed in the **default** namespace).

Results are then collected form **Vegeta**, for **user perceived latecies**, and from **Loki** for **control plane parameters**.

## Test Configuration

The test can be configured through the [`real-traffic-test.yaml`](./real-traffic-test.yaml) leveraging the following parameters:

```yaml
args:
- "-number-of-services=10"
- "-requests-per-second=50"
- "-critical-test=true"
- "-sources-of-interference=20"
- "-interfering-namespace=interference"
- "-time-between-interfering-bursts=10000"
- "-bucket-node=dessertw3"
- "-loki-url=http://<loki-pod-ip-address>:3100"
```

- ***Number of Services***: number of **Knative services** (if the test uses **RTResources**, each one is marked with a different **criticality level**, e.g., 10 services have criticality levels from 1 to 10)

- ***Requests per Second***: number of requests equally distributed to the **Knative services**.

- ***Critical Test***: if set to `true`, the test uses ***RTResources***, otherwise it relies on standard **Deployments**.

- ***Sources of Interference***: number of **RTResources**/**Deployments** to **create** and **delete** to generate interfering load bursts on the **control plane**.

- ***Interfering Namespace***: the namespace in which the interfering load is deployed.

- ***Time Between Interfering Bursts***: time between **control plane** interfering load bursts, e.g., **creation** or **deletion** of **RTResources**/**Deployments**.

- ***Bucket Node***: the node on which the interfering load is deployed.

- **Loki URL**: the **Loki** endpoint to query results logs (we rely on **IP address** since the **DNS resolution** might fail)

## Prerequisites

Knative configuration has to be patched to set **affinity fields** in the Knative managed pods. 

```bash
kubectl patch configmap config-features -n knative-serving --type merge -p '{"data":{"kubernetes.podspec-affinity":"Enabled"}}'
```

The **PREEMPT-FaaS controller** and the **CRD** for the **RTResource** must be installed in the cluster. Please refer to the **PREEMPT-FaaS** repositoy: <https://github.com/dessertlab/preempt-k8s>. The repository also contains a quick guide to setup the monitoring stack required by the test, including the persistent storage for results. See: https://github.com/dessertlab/preempt-k8s/tree/main/monitoring; https://github.com/dessertlab/preempt-k8s/tree/main/experiments/k8s-results-store; https://github.com/dessertlab/preempt-k8s/tree/main/experiments/test-pods.

**DISCLAIMER**: Make sure all your nodes have the same time zone, since the experiment will run on a worker node and will try to retrieve logs generated in the control plane, with timestamps related to its time zone.

## Relevant Notes

There are a few differences with the standard *Real Traffic Test*.

1) There are no **init-containers** for any of the Knative services.

2) There is no **response latency** introduced on purpose.

3) The **payload** size is fixed and set to `10,000` bytes.

4) The **activator** is never set to be `Always in path`, following the usual Knative flow.

All these modifications were mandatory to make all Knative services, and relative response latencies, equivalent. In this scenario, end results are purely influenced by the Kube-Manager/PREEMPT-FaaS orchestration times.

## Results Collection

Currently, the results are stored in a **K8s persistent volume** referenced in the `real-traffic-test.yaml`. The file in the path `/experiment`.

A quick guide to set it up is proposed in the **PREEMPT-FaaS** repository: <https://github.com/dessertlab/preempt-k8s/tree/main/experiments/k8s-results-store>.

The reference in the experiment manifest is the following:

```yaml
spec:
  <other-configurations>
    volumeMounts:
      - name: experiments-results
        mountPath: /experiments
  volumes:
    - name: experiments-results
      persistentVolumeClaim:
        claimName: experiments-results
```

If you use a custom storage, make sure to update the manifest.

The script saves the results in the following directories:

- **RTResource** -> `/experiments/knative/real-traffic-test/preempt-k8s`

- **Deployment** -> `/experiments/knative/real-traffic-test/kube-manager`

Each experiment run is then stored in a sub-directory named with the timestamp of the experiment. The contents of this directory will be two files: ***vegeta_metrics.txt*** and ***audit_logs.json***.

***vegeta_metrics.txt*** also contains details on the experiment configuration used for the run.

## Test Setup

Move to this repository root folder (remember that all the files discussed and that need to be edited are under the [`real-traffic-test`](../real-traffic-test) folder).

Let's create the secret with the info needed by the test pod.

```bash
export KO_DOCKER_REPO="docker.io/<your-docker-repo>"
export SYSTEM_NAMESPACE="knative-serving"
export JOB_NAME="local"
export BUILD_ID="local"

kubectl create secret generic performance-test-config -n default \
  --from-literal=kodockerrepo="${KO_DOCKER_REPO}" \
  --from-literal=systemnamespace="${SYSTEM_NAMESPACE}" \
  --from-literal=jobname="${JOB_NAME}" \
  --from-literal=buildid="${BUILD_ID}"
```

When yout run of the experiment is over, delete the secret with the following command:

```bash
kubectl delete secret performance-test-config -n default
```

Now, we must build and push the server image used by the Knative services that the test will create.

```bash
KO_DOCKER_REPO=docker.io/<your-docker-repo> ko resolve --sbom=none -B -f ./test/test_images/runtime/service.yaml
```

Now we build and push the test and update its K8s manifest.

The [`real-traffic-test.yaml`](./real-traffic-test.yaml) `image` field should look like this (with the `ko` reference). If not, edit the file (this is a mandatory step when re-building and re-pushing the test).

```yaml
containers:
    image: ko://knative.dev/serving/test/performance/benchmarks/real-traffic-test
```

Now launch the following command:

```bash
KO_DOCKER_REPO=docker.io/<your-docker-repo> ko resolve --sbom=none -B -f ./test/performance/benchmarks/real-traffic-test/real-traffic-test.yaml
```

The output of the previous command will show you the test manifest file with the `image` field updated. Copy its value and edit again the [`real-traffic-test.yaml`](./real-traffic-test.yaml) file, updating said field.

## Run the Test

Assuming you are in the [`real-traffic-test`](../real-traffic-test) directory.

```bash
./real-traffic-test.sh -f real-traffic-test.yaml -i <number-of-iterations> -t <RTResource|Deployment> 
```
**Note**: if you set the `-t` flag to `RTResource`, make sure that the `critical-test` parameter in the test manifest is set to `true`, otherwise the test will produce erroneous results. Conversely, if you set the `-t` flag to `Deployment`, make sure that the `critical-test` parameter in the test manifest is set to `false`.

Once the test is over, deploy a pod, in the `default` namespace, that mounts the same volume used for results. Enter the pod and move to the results directory. For reference, you can deploy the `test-pod` in : https://github.com/dessertlab/preempt-k8s/tree/main/experiments/test-pods/test-pod.yaml.

```bash
kubectl exec -it <test-pod-name> -n default -- <command-to-open-shell>
```

If you are using the provided `test-pod`, the command to enter the pod shell is:

```bash
kubectl exec -it test-pod -n default -- sh
```

Move to the location of your test results (any pod that mounts the same volume used for results).

## Process Results

There are three **Python scripts** available to process the results collected.

`analyze_preempt_k8s_results.py` and `analyze_kube_manager_results.py` process per experiment **metrics**.

`aggregate_results.py` process the previous **metrics** to produce **general statistics files** based on said data.

### analyze_preempt_k8s_results.py

**Input Parameters**: the path of the directory containing all the experiments results (the one containing all sub-directories named after the timestamp of each experiment).

**Output**: a ***.csv*** file named with the same timestamp of the experiment for each experiment, each in the respective sub-directory; this script should only be used to process results obtained when Knative is using RTResources (erroneus values will be produced otherwise).

The script will calculate for each service the following **metrics**:

1) ***criticality_level*** -> the priority level of the Knative service (a lower value means higher priority);

2) ***mean_latency*** -> mean response latency (the one perceived by the user);

3) ***scale_up_number*** -> number of **scale-ups**;

4) ***starts_processing*** -> the mean time required by the **PREEMPT-FaaS controller** to start serving a **scale-up**;

5) ***pods_created*** -> the mean time required to create all of the pods required by a **scale-up**;

6) ***pods_started*** -> the mean time required to start all of the pods required by a **scale-up**.

**Usage Example**:
```bash
python analyze_preempt_k8s_results.py ./results/20-int-rtresources
```

### analyze_kube_manager_results.py

**Input Parameters**: the path of the directory containing all the experiments results (the one containing all sub-directories named after the timestamp of each experiment).

**Output**: a ***.csv*** file named with the same timestamp of the experiment for each experiment, each in the respective sub-directory; this script should only be used to process results obtained when Knative is using Deployments (erroneus values will be produced otherwise).

The script will calculate for each service the following **metrics**:

1) ***criticality_level*** -> the priority level of the Knative service (*NONE* since the **Kube-Manager** thus not leverage the priority concept during orchestration);

2) ***mean_latency*** -> mean response latency (the one perceived by the user);

3) ***scale_up_number*** -> number of **scale-ups**;

4) ***starts_processing*** -> the mean time required by the **Kube-Manager controller** to start serving a **scale-up**;

5) ***pods_created*** -> the mean time required to create all of the pods required by a **scale-up**;

6) ***pods_started*** -> the mean time required to start all of the pods required by a **scale-up**.

**Usage Example**:
```bash
python analyze_kube_manager_results.py ./results/20-int-deployments
```

### aggregate_results.py

**Input Parameters**: the path of the directory containing all the experiments results (the one containing all sub-directories named after the timestamp of each experiment).

**Output**: a ***results.csv*** with the mean value of each **metric**, ***box-plots*** and a ***.csv*** file for each **metric**; all output files are stored in the input directory.

The ***.csv*** for each metric contains for each service:

1) ***Mean***;

2) ***Min***;

3) ***Max***;

4) ***Variance***;

5) ***Std_Deviation***.

**Usage Example**:
```bash
python aggregate_results.py ./results/20-int
```

### Important Notes

- For an **RTResource use-case**, the most relevant audits from which we calculate our **metrics** are:

    1) **Knative** updates the **RTResource** of a service with the new *replicas* value;

    2) The **scale-up** request is being processed by the **PREEMPT-FaaS controller** when it updates the service **RTResource** status;

    3) The **PREEMPT-FaaS controller** starts to create pods.

    4) The **kubelet** informs the **Kube-apiserver** that the **pod** and its **containers** are up and running.

- For a **Deployment use-case**, the most relevant audits from which we calculate our **metrics** are:

    1) **Knative** updates the **Deployment** of a service with the new *replicas* value;

    2) The **scale-up** request is being processed when the first pod is being created by the **Kube-Manager**;

    3) The **kubelet** informs the **Kube-apiserver** that the **pod** and its **containers** are up and running.

For a detailed view of these logs, please refer to the **PREEMPT-FaaS repository**: <https://github.com/dessertlab/preempt-k8s/tree/main/experiments/examples/knative-application-example>.

### Metrics Definition

We add this section to clarify the definition of the metrics we calculate and to explain how we identify the relevant events in the collected logs.

- **Scale-Up**. The event at which the Knative autoscaler updates the replicas field of the Deployment or RTResource. A single iteration may include multiple scale-up events per service.

- **Starts Processing**. The event at which the controller begins handling a scale-up event, identified by its first interaction with the `kube-apiserver`. For the Kube-Manager controller, this corresponds to the creation of the first pod in the new replica set. For PREEMPT-FaaS, it coincides with updating the RTResource status condition to `Progressing`.

- **Pods Created**. The event at which all required pod objects for a scale-up are successfully created in the cluster. A pod is considered “created” once its API object exists, independently of container startup. For single-replica scale-ups under Kube-Manager, this event coincide with `Starts Processing`.

- **Pods Started**. The event at which all required pods are running and ready to receive traffic. Although this stage depends on the `Kubelet` behavior (which is outside the scope of this work), faster orchestration can advance pod scheduling and startup. Nevertheless, Kubelet queueing and internal mechanisms may still introduce variability.

## Monitoring Overhead

The test can be repeated by disabling **auditing** in K8s: https://github.com/dessertlab/preempt-k8s/tree/main/monitoring/audit.

**Instructions**: Repeat the test, for both Deployments and RTResources, with the same number of interfering sources and the same time between interfering bursts. Then, compare the results with the ones obtained with auditing enabled to understand the overhead introduced by this monitoring component through statistical tests.

### monitoring-overhead.py

**Input Parameters**: the paths to the results of multiple run with auditing enabled and disabled, respectively. The number of runs is set to 10 at the moment.

**Output**: console output with statistical analysis results. The script performs the following statistical tests:

1) **Normality Test** (Shapiro-Wilk): Verifies if the data follows a normal distribution for both groups.

2) **Variance Homogeneity Test** (Levene): Checks if the variances of the two groups are equal.

3) **Hypothesis Test**: Based on the normality and variance results, automatically selects and applies the appropriate test:
   - **Student's t-test**: When both groups are normally distributed with equal variances.
   - **Welch's t-test**: When both groups are normally distributed with unequal variances.
   - **Mann-Whitney U test**: When at least one group is not normally distributed.

The script tests the **null hypothesis**: *There is no significant difference between the two conditions (with and without monitoring enabled)*.

**Interpreting Results**: For each metric (currently `mean_latency`), the script reports:
- The normality test p-values for both groups (p_norm1 and p_norm2)
- The variance homogeneity test p-value (p_var)
- The statistical test used and its p-value
- The conclusion: if p-value < 0.05 (significance level α), the null hypothesis is rejected, indicating a **significant difference** introduced by the monitoring overhead; otherwise, we fail to reject the null hypothesis, suggesting **no significant difference**.

**Usage Example**:
```bash
python monitoring-overhead.py ./results/20-int ./results/20-int-monitoring-enabled
```

## Sensitivity Analysis

The following scripts perform the sensitivity analysis published in the paper.

### sensitivity-analysis.py

This script performs a sensitivity analysis by comparing orchestration metrics across different interference load levels (5, 10, and 20 interfering resources). It aggregates results from multiple experimental runs and generates a comprehensive boxplot visualization comparing both Kube-Manager (Vanilla K8s) and PREEMPT-FaaS controllers under varying stress conditions.

**Input Parameters**: Six directory paths, each containing experiment results with different numbers of interfering resources:
- Path to kube-manager results with 5 interfering resources
- Path to kube-manager results with 10 interfering resources
- Path to kube-manager results with 20 interfering resources
- Path to preempt-k8s results with 5 interfering resources
- Path to preempt-k8s results with 10 interfering resources
- Path to preempt-k8s results with 20 interfering resources

Each path should contain subdirectories with CSV files (exactly 10 runs per configuration at the moment).

**Output**: A PNG image file named `sensitivity_analysis_all_metrics.png` saved in `./results/sensitivity-analysis/`. The plot displays boxplots for three metrics (starts_processing, pods_created, pods_started) grouped by interference level, allowing visual comparison of how each controller responds to increasing control plane stress.

**Usage Example**:
```bash
python sensitivity-analysis.py ./results/kube-manager-5 ./results/kube-manager-10 ./results/kube-manager-20 ./results/preempt-k8s-5 ./results/preempt-k8s-10 ./results/preempt-k8s-20
```

### sensitivity-analysis-5-threads.py

This script analyzes the impact of using 5 parallel threads in the PREEMPT-FaaS controller compared to the baseline Kube-Manager configuration. It compares orchestration metrics between standard Kube-Manager (with 20 interfering resources) and PREEMPT-FaaS running with 5 threads (also with 20 interfering resources).

**Input Parameters**: Two directory paths:
- Path to kube-manager results with 20 interfering resources
- Path to preempt-k8s results with 20 interfering resources using 5 threads

Each path should contain subdirectories with CSV files (exactly 10 runs per configuration).

**Output**: A CSV file named `sensitivity_analysis_5_threads.csv` saved in `./results/sensitivity-analysis/`. The file contains average values and variances for each metric (starts_processing, pods_created, pods_started) for both controllers, enabling quantitative comparison of the threading optimization.

**Usage Example**:
```bash
python sensitivity-analysis-5-threads.py ./results/kube-manager-20 ./results/preempt-k8s-20-5-threads
```
### scatter-plot.py

This scrpit si not available for use yet.
