/*
Copyright 2024 The Knative Authors

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

package v1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"knative.dev/pkg/apis"
	duckv1 "knative.dev/pkg/apis/duck/v1"
	"knative.dev/pkg/kmeta"
)

// +genclient
// +genreconciler
// +k8s:deepcopy-gen:interfaces=k8s.io/apimachinery/pkg/runtime.Object

// RTResource is a custom resource representing a real-time application.
// Users can use RTResources instead of Deployments.
// The use of such resources allow to orchestrate applications prioritizig them
// according to their criticality.
// Kubernetes will prioritize these applications' deployment requests with a custom controller
// designed to handle each application with a kernel thread scheduled with FIFO Linux priority
// assigned according to the Criticality field.
type RTResource struct {
	metav1.TypeMeta `json:",inline"`
	// +optional
	metav1.ObjectMeta `json:"metadata,omitempty"`

	// +optional
	Spec RTResourceSpec `json:"spec"`

	// +optional
	Status RTResourceStatus `json:"status,omitempty"`
}

// Verify that RTResource adheres to the appropriate interfaces.
var (
	// Check that RTResource may be validated and defaulted.
	_ apis.Validatable = (*RTResource)(nil)
	_ apis.Defaultable = (*RTResource)(nil)

	// Check that RTResource can be converted to higher versions.
	_ apis.Convertible = (*RTResource)(nil)

	// Check that we can create OwnerReferences to a RTResource.
	_ kmeta.OwnerRefable = (*RTResource)(nil)

	// Check that the type conforms to the duck Knative Resource shape.
	_ duckv1.KRShaped = (*RTResource)(nil)
)

// RTResourceSpec holds the desired state of the RTResource (from the client).
type RTResourceSpec struct {
	// Namespace where the resource will be deployed
	// +optional
	Namespace string `json:"namespace,omitempty"`

	// Number of desired replicas. This is a pointer to distinguish between explicit
	// zero and not specified.
	// +optional
	Replicas *int32 `json:"replicas,omitempty"`

	// Selector is a label identifying the pods managed by this resource.
	// It must match the pod template's labels.
	// +optional
	Selector *metav1.LabelSelector `json:"selector,omitempty"`

	// Criticality level (1-80)
	Criticality int32 `json:"criticality"`

	// Template describes the pods that will be created.
	// +optional
	Template corev1.PodTemplateSpec `json:"template"`
}

// RTResourceConditionType is a valid value for RTResourceCondition.Type
type RTResourceConditionType string

// RTResourceStatus is the status for a RTResource resource
type RTResourceStatus struct {
	duckv1.Status `json:",inline"`

	// DesiredReplicas is the desired number of replicas
	// +optional
	DesiredReplicas int32 `json:"desiredReplicas,omitempty"`

	// Replicas is the actual number of ready replicas observed by the autoscaler
	// +optional
	Replicas int32 `json:"replicas,omitempty"`
}

// +k8s:deepcopy-gen:interfaces=k8s.io/apimachinery/pkg/runtime.Object

// RTResourceList is a list of RTResource resources
type RTResourceList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata"`

	Items []RTResource `json:"items"`
}

// GetStatus retrieves the status of the RTResource. Implements the KRShaped interface.
func (t *RTResource) GetStatus() *duckv1.Status {
	return &t.Status.Status
}
