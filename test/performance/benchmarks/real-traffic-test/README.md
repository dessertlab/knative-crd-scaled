# Real Traffic Test Benchmark

This test is a modified version of the *Real Traffic Test* found in the **Knative** codebase.

## Purpose of the Test

This test purpose is to compare the performance of the **kube-Manger** controller for **Deployments** and **ReplicaSets** against the **Preempt-K8s** custom controller for **RTResources** (our real-time version of the standard K8s Deployments).

We deploy a given number of services managed by Knative with a concurrency level set to *5*. If the test is *critical*, Knative relies on **RTResources** setting the proper priorities to each service to handle. otherwise, it uses standard **Deployments**. The test starts by deploying these services and waiting for them to **scale to zero** and to scrape out old logs.

Using **Vegeta**, the test generates a given number of requests per second sent equally to each service in **round-robin**. This causes a scale up of each service according to percieved load and the Knative **autoscaler**'s calculations. The tests lasts 1 minute, even though the scale up stabilizes after a few seconds.

At the same time, other parallel routines generate an interfering load on the control plane by creating or deleting other **RTResources**/**Deployments**. The interfering pods are assigned to a bucket node, not used by the Knative services' pods to exclude their interference on the **nodes** and relative **Kubelets**. We also use a separate namespace to exclude these requests from the collected pods (the main Knative services are deployed in the **default** namespace).

Results are then collected form **Vegeta**, for **user perceived latecies**, and from **Loki** for **control plane parameters**.

## Test Parameters

The test can be configured by modifing the ***real-traffic-test.yaml*** file in the following section:

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

- ***Number of Services***: number of **Knative services** (if the test uses **RTResources**, each one is marked with a different **criticality level**, e.g., 10 seervices have criticality levels from 1 to 10)

- ***Requests per Second***: number of requests devided equally between the **Knative services**.

- ***Critical Test***: if set to *true*, the test uses ***RTResources***, otherwise it relies on standard **Deployments**.

- ***Sources of Interference***: number of **RTResources**/**Deployments** to **create** or **delete** to create interfering load on the **control plane**.

- ***Interfering Namespace***: the namespace in which the interfering load is deployed.

- ***Time Between Interfering Bursts***: time between **control plane** interfering load, e.g., **creation** or **deletion** of **RTResources**/**Deployments**.

- ***Bucket Node***: the node on which the interfering load is deployed.

- **Loki URL**: the **Loki** endpoint to query results logs (we rely on **IP address** since the **DNS resolution** could fail)

## Prerequisites

Knative configuration has to be patched to set **affinity fields** in the Knative managed pods. 

```bash
kubectl patch configmap config-features -n knative-serving --type merge -p '{"data":{"kubernetes.podspec-affinity":"Enabled"}}'
```

The **Preempt-K8s controller** and the **CRD** for the **RTResource** must be installed in the cluster. Please refer to the **Preempt-K8s** repositoy: <https://github.com/dessertlab/rt-kubernetes>.

## Relevant Notes

There are a few differences with the standard *Real Traffic Test*.

1) There is no **init-container** for any of the Knative services.

2) There is no **response latency** introduce on purpose.

3) The **payload** size is fixed and set to 10,000 bytes.

4) The **activator** is never set to be "*Always in path*" following the usual Knative flow.

All these modifications were necessary to make all Knative services and relative response latencies equal. In this scenario, the only influence on the results metrics is purely due to K8s and the hardware which makes up the cluster.

## Results Collection

Currently, the results are stored in a **K8s persistent volume** referenced in the ***real-traffic-test.yaml*** file in the path "*/experiment*"

Create your own persisten volume with *ReadWriteMany* option and reference it in the experiment manifest, or create one the same name: *experiments-results*.

A quick guide is proposed in the **Preempt-K8s** repository: <https://github.com/dessertlab/rt-kubernetes/tree/main/experiments/k8s-results-store>.

The script saves the results in the following directories:

- **RTResource** -> */experiments/knative/real-traffic-test/preempt-k8s*

- **Deployment** -> */experiments/knative/real-traffic-test/kube-manager*

Each experiment run is then stored in a sub-directory named with the timestamp of the experiment. The contents of this directory will be two files: ***vegeta_metrics.txt*** and ***audit_logs.json***.

***vegeta_metrics.txt*** also contains details on the experiment configuration.

## Test Setup

Move to this repository root folder (remember that all the files discussed and that need to be edited are under the ***real-traffic-test*** folder).

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

When you don't need it anymore, delete it with the following command:

```bash
kubectl delete secret performance-test-config -n default
```

Now, we must build and push the server image used by the Knative services that the test will create.

```bash
KO_DOCKER_REPO=docker.io/<your-docker-repo> ko resolve --sbom=none -B -f ./test/test_images/runtime/service.yaml
```

Now we build and push the test and update its K8s manifest.

The ***real-traffic-test.yaml*** *image* field should look like this (with the "*ko*" reference). If not, edit the file (this is a necessary step when re-building and re-pushing the test).

```yaml
containers:
    image: ko://knative.dev/serving/test/performance/benchmarks/real-traffic-test
```

Now launch the following command:

```bash
KO_DOCKER_REPO=docker.io/<your-docker-repo> ko resolve --sbom=none -B -f ./test/performance/benchmarks/real-traffic-test/real-traffic-test.yaml
```

The output of the previous command will show you the test's manifest file with the *image* field updated. Copy its value and edit the ***real-traffic-test.yaml*** file updating said field.

## Execute the Test

Assuming you are in the ***real-traffic-test*** directory.

```bash
./real-traffic-test.sh -f real-traffic-test.yaml -i <number-of-iterations> -t <RTResource|Deployment> 
```

Move to the location of your test results (any pod that mounts the same volume used for results).

## Process Results

There are three **Python scripts** available to process the results collected.

***analyze_preempt_k8s_results.py*** and ***analyze_kube_manager_results.py*** process per experiment **metrics**.

***aggregate_results.py*** process the previous **metrics** to produce **general statistics** upon them.

### analyze_preempt_k8s_results.py

**Input Parameters**: the path of the directory containing all the experiments results (the one containing all sub-directories named after the timestamp of each experiment).

**Output**: a ***.csv*** file named with the same timestamp of the experiment for each experiment, each in the respective sub-directory; this script should only be used to process results obtained when Knative is using RTResources (erroneus values will be produced otherwise).

The script will calculate for each service the following **metrics**:

1) ***criticality_level*** -> the priority level of the Knative service (a lower value means higher priority);

2) ***mean_latency*** -> mean response latency (the one perceived by the user);

3) ***scale_up_number*** -> number of **scale-ups**;

4) ***starts_processing*** -> the mean time required by the **Preempt-K8s controller** to start serving a **scale-up**;

5) ***pods_created*** -> the mean time required to create all of the pods required by a **scale-up**;

6) ***pods_started*** -> the mean time required to start all of the pods required by a **scale-up**.

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

### aggregate_results.py

**Input Parameters**: the path of the directory containing all the experiments results (the one containing all sub-directories named after the timestamp of each experiment).

**Output**: a ***results.csv*** with the mean value of each **metric**, ***box-plots*** and a ***.csv*** file for each **metric**; all output files are stored in the input directory.

The ***.csv*** for each metric contains for each service:

1) ***Mean***;

2) ***Min***;

3) ***Max***;

4) ***Variance***;

5) ***Std_Deviation***.

### Important Notes

- For an **RTResource use-case**, the most relevant audits from which we calculate our **metrics** are:

    1) **Knative** updates the **RTResource** of a service with the new *replicas* value;

    2) The **scale-up** request is being processed by the **Preempt-K8s controller** when it updates the service **RTResource** status;

    3) The **Preempt-K8s controller** starts to create pods.

    4) The **kubelet** informs the **Kube-apiserver** that the **pod** and its **containers** are up and running.

- For a **Deployment use-case**, the most relevant audits from which we calculate our **metrics** are:

    1) **Knative** updates the **Deployment** of a service with the new *replicas* value;

    2) The **scale-up** request is being processed when the first pod is being created by the **Kube-Manager**;

    3) The **kubelet** informs the **Kube-apiserver** that the **pod** and its **containers** are up and running.

For a detailed view of these logs, please refer to the **Preempt-K8s repository**: <https://github.com/dessertlab/rt-kubernetes/tree/main/experiments/examples/knative-application-example>.
