/*
Copyright 2018 The Knative Authors

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

package resources

import (
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"knative.dev/pkg/apis"
	"knative.dev/pkg/kmeta"
	autoscalingv1alpha1 "knative.dev/serving/pkg/apis/autoscaling/v1alpha1"
	rtresourcev1 "knative.dev/serving/pkg/apis/rtresource/v1"
	v1 "knative.dev/serving/pkg/apis/serving/v1"
	"knative.dev/serving/pkg/reconciler/revision/resources/names"
)

// MakePA makes a Knative Pod Autoscaler resource from a revision.
func MakePA(rev *v1.Revision, deployment *appsv1.Deployment, rtresource *rtresourcev1.RTResource, targetKind string) *autoscalingv1alpha1.PodAutoscaler {
	var apiVersion, kind, name string

	switch targetKind {
	case "Deployment":
		apiVersion = "apps/v1"
        kind = targetKind
        name = names.Deployment(rev)
	case "RTResource":
		apiVersion = "rtgroup.critical.com/v1"
        kind = targetKind
        name = names.RTResource(rev)
	default:
		apiVersion = "apps/v1"
        kind = targetKind
        name = names.Deployment(rev)
	}

	return &autoscalingv1alpha1.PodAutoscaler{
		ObjectMeta: metav1.ObjectMeta{
			Name:            names.PA(rev),
			Namespace:       rev.Namespace,
			Labels:          makeLabels(rev),
			Annotations:     podAutoscalerAnnotations(rev),
			OwnerReferences: []metav1.OwnerReference{*kmeta.NewControllerRef(rev)},
		},
		Spec: autoscalingv1alpha1.PodAutoscalerSpec{
			ContainerConcurrency: rev.Spec.GetContainerConcurrency(),
			ScaleTargetRef: corev1.ObjectReference{
				APIVersion: apiVersion,
				Kind:       kind,
				Name:       name,
			},
			ProtocolType: rev.GetProtocol(),
			Reachability: reachability(rev, deployment, rtresource, targetKind),
		},
	}
}

func reachability(rev *v1.Revision, deployment *appsv1.Deployment, rtresource *rtresourcev1.RTResource, targetKind string) autoscalingv1alpha1.ReachabilityType {
	// check infra failures
	infraFailure := false
	for _, cond := range []apis.ConditionType{
		v1.RevisionConditionResourcesAvailable,
		v1.RevisionConditionContainerHealthy,
	} {
		if c := rev.Status.GetCondition(cond); c != nil && c.IsFalse() {
			infraFailure = true
			break
		}
	}

	switch targetKind {
	case "Deployment":
		if infraFailure && deployment != nil && deployment.Spec.Replicas != nil {
			// If we have an infra failure and no ready replicas - then this revision is unreachable
			if *deployment.Spec.Replicas > 0 && deployment.Status.ReadyReplicas == 0 {
				return autoscalingv1alpha1.ReachabilityUnreachable
			}
		}
	case "RTResource":
		if infraFailure && rtresource != nil && rtresource.Spec.Replicas != nil {
		// If we have an infra failure and no ready replicas - then this revision is unreachable
			if *rtresource.Spec.Replicas > 0 && rtresource.Status.Replicas == 0 {
				return autoscalingv1alpha1.ReachabilityUnreachable
			}
		}
	default:
		if infraFailure && deployment != nil && deployment.Spec.Replicas != nil {
			// If we have an infra failure and no ready replicas - then this revision is unreachable
			if *deployment.Spec.Replicas > 0 && deployment.Status.ReadyReplicas == 0 {
				return autoscalingv1alpha1.ReachabilityUnreachable
			}
		}
	}

	switch rev.GetRoutingState() {
	case v1.RoutingStateActive:
		return autoscalingv1alpha1.ReachabilityReachable
	case v1.RoutingStateReserve:
		return autoscalingv1alpha1.ReachabilityUnreachable
	default:
		return autoscalingv1alpha1.ReachabilityUnknown
	}
}
