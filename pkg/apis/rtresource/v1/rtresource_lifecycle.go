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
	"k8s.io/apimachinery/pkg/runtime/schema"
	"knative.dev/pkg/apis"
	duckv1 "knative.dev/pkg/apis/duck/v1"
)

// GetGroupVersionKind returns the GroupVersionKind.
func (*RTResource) GetGroupVersionKind() schema.GroupVersionKind {
	return SchemeGroupVersion.WithKind("RTResource")
}

// TransformRTResourceStatus transforms the RTResourceStatus into a
// duckv1.Status that uses ConditionSets to propagate failures and expose
// a top-level happy state, per our condition conventions.
func TransformRTResourceStatus(original *RTResourceStatus) *duckv1.Status {
	if original == nil {
		return &duckv1.Status{}
	}

	status := &duckv1.Status{
		ObservedGeneration: original.ObservedGeneration,
	}

	condSet.Manage(status).InitializeConditions()

	for _, cond := range original.Conditions {
		var condType apis.ConditionType
		switch apis.ConditionType(cond.Type) {
		case apis.ConditionReady:
			condType = apis.ConditionReady
		case RTResourceConditionProgressing:
			condType = RTResourceConditionProgressing
		default:
			continue
		}

		switch cond.Status {
		case corev1.ConditionTrue:
			condSet.Manage(status).MarkTrue(condType)
		case corev1.ConditionFalse:
			condSet.Manage(status).MarkFalse(condType, cond.Reason, cond.Message)
		case corev1.ConditionUnknown:
			condSet.Manage(status).MarkUnknown(condType, cond.Reason, cond.Message)
		}
	}

	return status
}
