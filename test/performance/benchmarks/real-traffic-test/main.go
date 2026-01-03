/*
Copyright 2022 The Knative Authors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"math"
	"math/rand"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	vegeta "github.com/tsenart/vegeta/v12/lib"
	"golang.org/x/sync/errgroup"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/dynamic"
	netapi "knative.dev/networking/pkg/apis/networking"
	"knative.dev/pkg/environment"
	"knative.dev/pkg/injection"
	pkgTest "knative.dev/pkg/test"
	"knative.dev/serving/pkg/apis/autoscaling"
	"knative.dev/serving/pkg/apis/config"
	"knative.dev/serving/pkg/apis/serving"
	ktest "knative.dev/serving/pkg/testing/v1"
	"knative.dev/serving/test"
	v1test "knative.dev/serving/test/v1"

	"knative.dev/pkg/signals"

	crytporand "crypto/rand"
)

const (
	namespace     = "default"
	benchmarkName = "Knative Serving real traffic test"
	serviceName   = "perftest"

	duration = 1 * time.Minute

	// Test configuration
	// Defines the latency of target
	minLatency = 0 * time.Second
	maxLatency = 0 * time.Second

	// Defines the delay that a Knative Service has for startup (init-container causes the delay)
	minStartupLatency = 0 * time.Second
	maxStartupLatency = 0 * time.Second

	// Defines the payloads that are sent on the vegeta requests
	minPayloadSizeBytes = 10_000
	maxPayloadSizeBytes = 10_000
)

var (
	numberOfServices      = flag.Int("number-of-services", 10, "The number of Knative Services to create")
	rps                   = flag.Int("requests-per-second", 300, "The number of requests per second to send")
	criticalTest          = flag.Bool("critical-test", false, "Whether this is a critical test or not")
	sourcesOfInterference = flag.Int("sources-of-interference", 10, "The number of sources of interference to create")
	interferingNamespace  = flag.String("interfering-namespace", "realtime", "The namespace where interfering resources are created")
	bucketNode            = flag.String("bucket-node", "dessertw3", "The node where interfering resources are scheduled")
	lokiURL               = flag.String("loki-url", "http://loki.observability.svc.cluster.local:3100", "Loki endpoint URL")
)

type serviceConfig struct {
	resourceObjects *v1test.ResourceObjects

	activatorAlwaysInPath bool
	latency               int64
	startupLatency        int64
	payload               []byte
}

type LokiQueryRequest struct {
	Name  string `json:"name"`
	Query string `json:"query"`
}

type LokiResponse struct {
	Status string `json:"status"`
	Data   struct {
		ResultType string `json:"resultType"`
		Result     []struct {
			Stream map[string]string `json:"stream"`
			Values [][]string        `json:"values"`
		} `json:"result"`
	} `json:"data"`
}

func main() {
	if *rps >= 2500 {
		log.Fatal("One test container cannot create more than 2500 RPS without errors. Consider starting this test in parallel.")
	}

	ctx := signals.NewContext()
	ctx, cancel := context.WithTimeout(ctx, 30*time.Minute)
	defer cancel()

	// To make testing.T work properly
	testing.Init()

	env := environment.ClientConfig{}

	// The local domain is directly resolvable by the test
	flag.Set("resolvabledomain", "true")

	// manually parse flags to avoid conflicting flags
	flag.Parse()

	cfg, err := env.GetRESTConfig()
	if err != nil {
		log.Fatalf("failed to get kubeconfig %s", err)
	}

	ctx, _ = injection.EnableInjectionOrDie(ctx, cfg)

	clients, err := test.NewClients(cfg, namespace)
	if err != nil {
		log.Fatal("Failed to setup clients: ", err)
	}

	// Dynamic client to create interfering resources
	dynamicClient, err := dynamic.NewForConfig(cfg)
	if err != nil {
		log.Fatalf("Failed to create dynamic client: %v", err)
	}

	log.Printf("Creating %d Knative Services", *numberOfServices)
	services, cleanup, err := createServices(clients, *numberOfServices)
	if err != nil {
		log.Fatalf("Failed to create services: %v", err)
	}
	defer cleanup()

	log.Print("Waiting for services to scale to zero and to scrape out initial logs")
	time.Sleep(100 * time.Second)
	testStartTime := time.Now()

	// We start interference routines
	interferenceCtx, cancelInterference := context.WithCancel(ctx)
	defer cancelInterference()

	log.Printf("Starting %d interference routines", *sourcesOfInterference)

	interferenceGroup := errgroup.Group{}
	if *criticalTest {
		log.Print("Using RTResource interference resources")

		for i := 0; i < *sourcesOfInterference; i++ {
			routineID := i
			interferenceGroup.Go(func() error {
				return runRTResourceInterferenceRoutine(interferenceCtx, dynamicClient, routineID)
			})
		}
	} else {
		log.Print("Using Deployment interference resources")

		for i := 0; i < *sourcesOfInterference; i++ {
			routineID := i
			interferenceGroup.Go(func() error {
				return runDeploymentInterferenceRoutine(interferenceCtx, dynamicClient, routineID)
			})
		}
	}

	// We prepare vegeta targets
	log.Print("Creating vegeta targets")

	targets := []vegeta.Target{}
	for _, svc := range services {
		t := vegeta.Target{
			Method: http.MethodPost,
			URL:    fmt.Sprintf("http://%s.default.svc.cluster.local?sleep=%d", svc.resourceObjects.Service.Name, svc.latency),
			Body:   svc.payload,
		}
		targets = append(targets, t)

		log.Printf("Name: %s, startup-latency: %ds, latency: %dms, payload: %dKb, activator-always-in-path: %v",
			svc.resourceObjects.Service.Name, svc.startupLatency, svc.latency, len(svc.payload)/1000, svc.activatorAlwaysInPath)
	}

	// Send configured RPS round-robin over all services,
	// while the request timeout is based on the max delays + 20 seconds
	log.Printf("Starting vegeta attack for with %v RPS for duration: %v", *rps, duration)
	rate := vegeta.Rate{Freq: *rps, Per: time.Second}
	attacker := vegeta.NewAttacker(vegeta.Timeout(maxLatency + maxStartupLatency + 20*time.Second))
	targeter := vegeta.NewStaticTargeter(targets...)

	results := attacker.Attack(targeter, rate, duration, "real-traffic-test")

	metricResults := &vegeta.Metrics{}
	serviceMetrics := make(map[string]*vegeta.Metrics)
	for _, svc := range services {
		serviceMetrics[svc.resourceObjects.Service.Name] = &vegeta.Metrics{}
	}

LOOP:
	for {
		select {
		case <-ctx.Done():
			// If we time out or the pod gets shutdown via SIGTERM then start to
			// clean thing up.
			break LOOP

		case res, ok := <-results:
			if ok {
				if res.Error != "" {
					log.Printf("error occurred calling target. Err: %s, url: %s, method: %s", res.Error, res.URL, res.Method)
				}
				metricResults.Add(res)
				serviceName := extractServiceNameFromURL(res.URL)
				if metrics, ok := serviceMetrics[serviceName]; ok {
					metrics.Add(res)
				}
			} else {
				// If there are no more results, then we're done!
				break LOOP
			}
		}
	}

	// Compute latency percentiles
	metricResults.Close()
	for _, metrics := range serviceMetrics {
		metrics.Close()
	}

	testEndTime := time.Now()

	log.Print("Waiting for logs to be published to Loki")
	time.Sleep(30 * time.Second)

	// We stop interference routines
	log.Print("Stopping interference routines")

	cancelInterference()
	if err := interferenceGroup.Wait(); err != nil {
		log.Printf("Interference routines error: %v", err)
	}

	// We ensure results directory exists
	timestamp := time.Now().Format("2006-01-02_15-04-05")

	resultsDir := ""
	if *criticalTest {
		resultsDir = fmt.Sprintf("/experiments/knative/real-traffic-test/preempt-k8s/%s", timestamp)
	} else {
		resultsDir = fmt.Sprintf("/experiments/knative/real-traffic-test/kube-manager/%s", timestamp)
	}
	if err := os.MkdirAll(resultsDir, 0755); err != nil {
		log.Printf("Failed to create results directory: %v", err)
	} else {
		log.Printf("Created results directory: %s", resultsDir)
	}

	vegetaOutputFile := filepath.Join(resultsDir, "vegeta_metrics.txt")
	lokiOutputFile := filepath.Join(resultsDir, "audit_logs.json")

	// We save the experimet results

	// We start from vegeta metrics
	log.Printf("Saving vegeta results to %s", vegetaOutputFile)
	if err := saveVegetaResults(vegetaOutputFile, metricResults, serviceMetrics, services); err != nil {
		log.Printf("Failed to save vegeta results: %v", err)
	}
	// We collect logs from Loki
	log.Printf("Collecting apiserver audit logs from Loki at %s", *lokiURL)

	lokiData, err := queryLokiLogs(ctx, testStartTime, testEndTime)
	if err != nil {
		log.Printf("Failed to query Loki: %v", err)
	}

	if lokiData != nil && len(lokiData) > 0 {
		if err := saveLokiData(lokiOutputFile, lokiData); err != nil {
			log.Printf("Failed to save Loki data: %v", err)
		}
	} else {
		log.Printf("No audit logs retrieved from Loki")
	}

	// We report vegeta results
	_ = vegeta.NewTextReporter(metricResults).Report(os.Stdout)

	if err := checkSLA(metricResults, rate); err != nil {
		cleanup()
		log.Fatal(err.Error())
	}

	log.Println("Real traffic test finished")
}

func createServices(clients *test.Clients, count int) ([]*serviceConfig, func(), error) {
	testNames := make([]*test.ResourceNames, count)

	// Initialize our service names.
	for i := range count {
		testNames[i] = &test.ResourceNames{
			Service: fmt.Sprintf("%s-%d", serviceName, i),
			// The crd.go helpers will convert to the actual image path.
			Image: test.Runtime,
		}
	}

	cleanupNames := func() {
		log.Println("Cleaning up all created services")
		for i := range count {
			test.TearDown(clients, testNames[i])
		}
	}

	objs := make([]*serviceConfig, count)
	begin := time.Now()
	commonSos := []ktest.ServiceOption{
		ktest.WithResourceRequirements(corev1.ResourceRequirements{
			// We set a small resource alloc so that we can pack more pods into the cluster,
			// also we do not set limits, as buffering in QP will take memory, and we'd be OOMKilled.
			Requests: corev1.ResourceList{
				corev1.ResourceCPU:    resource.MustParse("10m"),
				corev1.ResourceMemory: resource.MustParse("20Mi"),
			},
		}),
		ktest.WithServiceLabel(netapi.VisibilityLabelKey, serving.VisibilityClusterLocal),
	}

	g := errgroup.Group{}
	for i := range count {
		ndx := i
		g.Go(func() error {
			annotations := map[string]string{config.AllowHTTPFullDuplexFeatureKey: "Enabled"}

			activatorInPath := false
			if activatorInPath {
				annotations[autoscaling.TargetBurstCapacityKey] = "-1"
			}

			if *criticalTest {
				annotations["autoscaling.knative.dev/application-criticality-level"] = strconv.Itoa(ndx + 1)
			}

			annotations["autoscaling.knative.dev/metric"] = "concurrency"
			annotations["autoscaling.knative.dev/target"] = "5"

			sos := append(commonSos, ktest.WithConfigAnnotations(annotations))

			startupLatency := getRandomValue(int64(minStartupLatency.Seconds()), int64(maxStartupLatency.Seconds()))
			if startupLatency > 0 {
				sos = append(sos, ktest.WithInitContainer(corev1.Container{
					Name:  "slow-startup",
					Image: pkgTest.ImagePath(test.SlowStart),
					Args:  []string{"-sleep", strconv.FormatInt(startupLatency, 10)},
				}))
			}

			createdService, err := v1test.CreateServiceReady(&testing.T{}, clients, testNames[ndx], sos...)
			if err != nil {
				return fmt.Errorf("%02d: failed to create Ready service: %w", ndx, err)
			}
			latency := getRandomValue(minLatency.Milliseconds(), maxLatency.Milliseconds())
			payload, err := getRandomPayload(minPayloadSizeBytes, maxPayloadSizeBytes)
			if err != nil {
				return fmt.Errorf("%02d: failed to generate random payload: %w", ndx, err)
			}
			objs[ndx] = &serviceConfig{
				resourceObjects:       createdService,
				activatorAlwaysInPath: activatorInPath,
				latency:               latency,
				payload:               payload,
				startupLatency:        startupLatency,
			}
			return nil
		})
	}
	if err := g.Wait(); err != nil {
		return nil, nil, err
	}
	log.Print("Created all the services in ", time.Since(begin))
	return objs, cleanupNames, nil
}

func getRandomPayload(min int, max int) ([]byte, error) {
	num := getRandomValue(int64(min), int64(max))

	buf := make([]byte, num)
	_, err := crytporand.Read(buf)
	if err != nil {
		return nil, err
	}

	return buf, nil
}

func getRandomValue(min, max int64) int64 {
	if max <= min {
		return min
	} else {
		return rand.Int63n(max-min) + min
	}
}

/*
func getRandomBool() bool {
	return rand.Intn(2) == 1
}
*/

func extractServiceNameFromURL(url string) string {
	start := len("http://")
	if idx := strings.Index(url[start:], ".default"); idx != -1 {
		return url[start : start+idx]
	}
	return ""
}

func checkSLA(results *vegeta.Metrics, rate vegeta.ConstantPacer) error {
	// SLA 1: All requests should pass successfully.
	if len(results.Errors) == 0 {
		log.Println("SLA 1 passed. No errors occurred")
	} else {
		return fmt.Errorf("SLA 1 failed. Errors occurred: %d", len(results.Errors))
	}

	// SLA 2: making sure the defined vegeta rates is met
	if math.Round(results.Rate) == rate.Rate(time.Second) {
		log.Printf("SLA 2 passed. vegeta rate is %f", rate.Rate(time.Second))
	} else {
		return fmt.Errorf("SLA 2 failed. vegeta rate is %f, expected Rate is %f", results.Rate, rate.Rate(time.Second))
	}

	return nil
}

func runRTResourceInterferenceRoutine(ctx context.Context, dynamicClient dynamic.Interface, id int) error {
	rtResourceGVR := schema.GroupVersionResource{
		Group:    "rtgroup.critical.com",
		Version:  "v1",
		Resource: "rtresources",
	}

	resourceName := fmt.Sprintf("interfering-resource-%d", id)

	log.Printf("Interference routine %d started", id)

	for {
		select {
		case <-ctx.Done():
			log.Printf("Interference routine %d stopping", id)
			return nil
		default:
			// We define the interfering RTResource
			rtResource := &unstructured.Unstructured{
				Object: map[string]interface{}{
					"apiVersion": "rtgroup.critical.com/v1",
					"kind":       "RTResource",
					"metadata": map[string]interface{}{
						"name":      resourceName,
						"namespace": interferingNamespace,
					},
					"spec": map[string]interface{}{
						"namespace":   interferingNamespace,
						"replicas":    1,
						"criticality": *numberOfServices + 1,
						"selector": map[string]interface{}{
							"matchLabels": map[string]interface{}{
								"app-selector": fmt.Sprintf("interfering-app-%d", id),
							},
						},
						"template": map[string]interface{}{
							"metadata": map[string]interface{}{
								"name":      fmt.Sprintf("interfering-pod-%d", id),
								"namespace": interferingNamespace,
								"labels": map[string]interface{}{
									"test-label": fmt.Sprintf("interfering-label-%d", id),
								},
							},
							"spec": map[string]interface{}{
								"nodeSelector": map[string]interface{}{
									"kubernetes.io/hostname": bucketNode,
								},
								"containers": []interface{}{
									map[string]interface{}{
										"name":  "interfering-container",
										"image": "nginx:latest",
										"ports": []interface{}{
											map[string]interface{}{
												"containerPort": 80,
											},
										},
										"resources": map[string]interface{}{
											"requests": map[string]interface{}{
												"cpu":    "700m",
												"memory": "200Mi",
											},
											"limits": map[string]interface{}{
												"cpu":    "700m",
												"memory": "200Mi",
											},
										},
									},
								},
							},
						},
					},
				},
			}

			// We create and delete the RTResource in a loop to create interference

			// Creation step
			log.Printf("Interference %d: Creating RTResource", id)
			_, err := dynamicClient.Resource(rtResourceGVR).Namespace(*interferingNamespace).Create(
				ctx, rtResource, metav1.CreateOptions{})
			if err != nil {
				log.Printf("Interference %d: Failed to create RTResource: %v", id, err)
			} else {
				log.Printf("Interference %d: RTResource created", id)
			}

			// Wait 10s before deletion
			time.Sleep(10 * time.Second)

			// Deletetion step
			log.Printf("Interference %d: Deleting RTResource", id)
			err = dynamicClient.Resource(rtResourceGVR).Namespace(*interferingNamespace).Delete(
				ctx, resourceName, metav1.DeleteOptions{})
			if err != nil {
				log.Printf("Interference %d: Failed to delete RTResource: %v", id, err)
			} else {
				log.Printf("Interference %d: RTResource deleted", id)
			}

			// Wait 10s before new interfering cycle
			time.Sleep(10 * time.Second)
		}
	}
}

func runDeploymentInterferenceRoutine(ctx context.Context, dynamicClient dynamic.Interface, id int) error {
	deploymentGVR := schema.GroupVersionResource{
		Group:    "apps",
		Version:  "v1",
		Resource: "deployments",
	}

	resourceName := fmt.Sprintf("interfering-deployment-%d", id)

	log.Printf("Interference routine %d started", id)

	for {
		select {
		case <-ctx.Done():
			log.Printf("Interference routine %d stopping", id)
			return nil
		default:
			// We define the interfering Deployment
			deployment := &unstructured.Unstructured{
				Object: map[string]interface{}{
					"apiVersion": "apps/v1",
					"kind":       "Deployment",
					"metadata": map[string]interface{}{
						"name":      resourceName,
						"namespace": interferingNamespace,
					},
					"spec": map[string]interface{}{
						"replicas": 1,
						"selector": map[string]interface{}{
							"matchLabels": map[string]interface{}{
								"app-selector": fmt.Sprintf("interfering-app-%d", id),
							},
						},
						"template": map[string]interface{}{
							"metadata": map[string]interface{}{
								"name":      fmt.Sprintf("interfering-pod-%d", id),
								"namespace": interferingNamespace,
								"labels": map[string]interface{}{
									"test-label":   fmt.Sprintf("interfering-label-%d", id),
									"app-selector": fmt.Sprintf("interfering-app-%d", id),
								},
							},
							"spec": map[string]interface{}{
								"nodeSelector": map[string]interface{}{
									"kubernetes.io/hostname": bucketNode,
								},
								"containers": []interface{}{
									map[string]interface{}{
										"name":  "interfering-container",
										"image": "nginx:latest",
										"ports": []interface{}{
											map[string]interface{}{
												"containerPort": 80,
											},
										},
										"resources": map[string]interface{}{
											"requests": map[string]interface{}{
												"cpu":    "700m",
												"memory": "200Mi",
											},
											"limits": map[string]interface{}{
												"cpu":    "700m",
												"memory": "200Mi",
											},
										},
									},
								},
							},
						},
					},
				},
			}

			// We create and delete the Deployment in a loop to create interference

			// Creation step
			log.Printf("Interference %d: Creating Deployment", id)
			_, err := dynamicClient.Resource(deploymentGVR).Namespace(*interferingNamespace).Create(
				ctx, deployment, metav1.CreateOptions{})
			if err != nil {
				log.Printf("Interference %d: Failed to create Deployment: %v", id, err)
			} else {
				log.Printf("Interference %d: Deployment created", id)
			}

			// Wait 10s before deletion
			time.Sleep(10 * time.Second)

			// Deletetion step
			log.Printf("Interference %d: Deleting Deployment", id)
			err = dynamicClient.Resource(deploymentGVR).Namespace(*interferingNamespace).Delete(
				ctx, resourceName, metav1.DeleteOptions{})
			if err != nil {
				log.Printf("Interference %d: Failed to delete Deployment: %v", id, err)
			} else {
				log.Printf("Interference %d: Deployment deleted", id)
			}

			// Wait 10s before new interfering cycle
			time.Sleep(10 * time.Second)
		}
	}
}

func saveVegetaResults(outputFile string, metricResults *vegeta.Metrics, serviceMetrics map[string]*vegeta.Metrics, services []*serviceConfig) error {
	f, err := os.Create(outputFile)
	if err != nil {
		return fmt.Errorf("failed to create output file: %w", err)
	}
	defer f.Close()

	fmt.Fprintf(f, "=== Real Traffic Test Results ===\n")
	fmt.Fprintf(f, "\n")
	fmt.Fprintf(f, "\n")

	fmt.Fprintf(f, "== Test Configuration ==\n")
	fmt.Fprintf(f, "\n")
	fmt.Fprintf(f, "Services: %d\n", *numberOfServices)
	fmt.Fprintf(f, "RPS: %d\n", *rps)
	fmt.Fprintf(f, "Duration: %s\n", duration)
	fmt.Fprintf(f, "Min Latency: %s\n", minLatency)
	fmt.Fprintf(f, "Max Latency: %s\n", maxLatency)
	fmt.Fprintf(f, "Min Startup Latency: %s\n", minStartupLatency)
	fmt.Fprintf(f, "Max Startup Latency: %s\n", maxStartupLatency)
	fmt.Fprintf(f, "Min Payload Size (bytes): %d\n", minPayloadSizeBytes)
	fmt.Fprintf(f, "Max Payload Size (bytes): %d\n", maxPayloadSizeBytes)
	fmt.Fprintf(f, "Critical Test: %v\n", *criticalTest)
	fmt.Fprintf(f, "Sources of Interference: %d\n", *sourcesOfInterference)
	fmt.Fprintf(f, "Interfering Namespace: %s\n", *interferingNamespace)
	fmt.Fprintf(f, "Bucket Node: %s\n", *bucketNode)
	fmt.Fprintf(f, "\n")
	fmt.Fprintf(f, "\n")

	fmt.Fprintf(f, "== Test Results ==\n")
	fmt.Fprintf(f, "\n")

	fmt.Fprintf(f, "= Aggregated Results =\n")
	fmt.Fprintf(f, "\n")
	if err := vegeta.NewTextReporter(metricResults).Report(f); err != nil {
		log.Printf("Failed to write metrics: %v", err)
	}
	fmt.Fprintf(f, "\n")

	fmt.Fprintf(f, "= Per-Service Results =\n")
	fmt.Fprintf(f, "\n")

	for _, svc := range services {
		serviceName := svc.resourceObjects.Service.Name
		metrics := serviceMetrics[serviceName]

		fmt.Fprintf(f, "# Service: %s\n", serviceName)
		if *criticalTest {
			for i, s := range services {
				if s == svc {
					fmt.Fprintf(f, "Criticality Level: %d\n", i+1)
					break
				}
			}
		}
		fmt.Fprintf(f, "\n")

		if err := vegeta.NewTextReporter(metrics).Report(f); err != nil {
			log.Printf("Failed to write metrics for service %s: %v", serviceName, err)
		}

		fmt.Fprintf(f, "\n")
	}

	log.Printf("Results saved to %s", outputFile)
	return nil
}

func queryLokiLogs(ctx context.Context, startTime, endTime time.Time) ([]map[string]interface{}, error) {
	logQLQuery := `{job="kubernetes-audit"} | json`

	log.Printf("Executing Loki query: %s", logQLQuery)
	log.Printf("Time range: %s to %s", startTime.Format(time.RFC3339), endTime.Format(time.RFC3339))

	queryURL := fmt.Sprintf("%s/loki/api/v1/query_range", *lokiURL)

	params := url.Values{}
	params.Set("query", logQLQuery)
	params.Set("start", strconv.FormatInt(startTime.UnixNano(), 10))
	params.Set("end", strconv.FormatInt(endTime.UnixNano(), 10))
	params.Set("limit", "5000")
	params.Set("direction", "forward")

	fullURL := fmt.Sprintf("%s?%s", queryURL, params.Encode())

	req, err := http.NewRequestWithContext(ctx, "GET", fullURL, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to execute query: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("loki query failed with status %d: %s", resp.StatusCode, string(body))
	}

	var lokiResp LokiResponse
	if err := json.NewDecoder(resp.Body).Decode(&lokiResp); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	allLogs := []map[string]interface{}{}

	for _, result := range lokiResp.Data.Result {
		for _, value := range result.Values {
			if len(value) >= 2 {
				var logEntry map[string]interface{}
				if err := json.Unmarshal([]byte(value[1]), &logEntry); err != nil {
					log.Printf("Warning: Failed to parse log entry: %v", err)
					continue
				}

				timestampNano, err := strconv.ParseInt(value[0], 10, 64)
				if err != nil {
					log.Printf("Warning: Failed to parse timestamp: %v", err)
					timestampNano = 0
				}

				formattedLog := map[string]interface{}{
					"timestamp":       value[0],
					"timestamp_human": time.Unix(0, timestampNano).Format(time.RFC3339),
					"log":             logEntry,
				}

				allLogs = append(allLogs, formattedLog)
			}
		}
	}

	log.Printf("Retrieved %d audit log entries", len(allLogs))
	return allLogs, nil
}

func saveLokiData(filename string, data []map[string]interface{}) error {
	f, err := os.Create(filename)
	if err != nil {
		return fmt.Errorf("failed to create file: %w", err)
	}
	defer f.Close()

	encoder := json.NewEncoder(f)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(data); err != nil {
		return fmt.Errorf("failed to encode data: %w", err)
	}

	log.Printf("Saved %d log entries to %s", len(data), filename)
	return nil
}
