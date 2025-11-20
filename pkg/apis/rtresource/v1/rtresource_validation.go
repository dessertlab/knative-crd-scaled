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
	"context"

	"knative.dev/pkg/apis"
	"knative.dev/serving/pkg/apis/serving"
)

// Validate makes sure that RTResource is properly configured.
func (r *RTResource) Validate(ctx context.Context) (errs *apis.FieldError) {
	// If we are in a status sub resource update, the metadata and spec cannot change.
	// So, to avoid rejecting controller status updates due to validations that may
	// have changed (i.e. due to config-defaults changes), we elide the metadata and
	// spec validation.
	if !apis.IsInStatusUpdate(ctx) {
		errs = errs.Also(serving.ValidateObjectMetadata(ctx, r.GetObjectMeta(), false))
		errs = errs.ViaField("metadata")

		ctx = apis.WithinParent(ctx, r.ObjectMeta)
		errs = errs.Also(r.Spec.Validate(apis.WithinSpec(ctx)).ViaField("spec"))
	}

	return errs
}

// Validate implements apis.Validatable
func (r *RTResourceSpec) Validate(ctx context.Context) *apis.FieldError {
	var errs *apis.FieldError

	// Validate Criticality (1-80)
	if r.Criticality < 1 || r.Criticality > 80 {
		errs = errs.Also(apis.ErrOutOfBoundsValue(r.Criticality, 1, 80, "criticality"))
	}

	// Validate Replicas (if specified, must be >= 0)
	if r.Replicas != nil && *r.Replicas < 0 {
		errs = errs.Also(apis.ErrOutOfBoundsValue(*r.Replicas, 0, int32(^uint32(0)>>1), "replicas"))
	}

	// NOTE: Selector validation is handled by Kubernetes (metav1.LabelSelector is validated).
	// The reconciler should ensure it matches Template.Labels.

	// NOTE: Template (PodTemplateSpec) validation is delegated to Kubernetes.
	// Invalid PodSpecs will be caught when the Pods are created.
	// The same goes for the Namespace field.

	return errs
}
