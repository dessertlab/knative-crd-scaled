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
)

// SetDefaults implements apis.Defaultable
func (r *RTResource) SetDefaults(ctx context.Context) {
	ctx = apis.WithinParent(ctx, r.ObjectMeta)
	r.Spec.SetDefaults(apis.WithinSpec(ctx))
}

// SetDefaults implements apis.Defaultable
func (rs *RTResourceSpec) SetDefaults(ctx context.Context) {
	// Set default namespace if not specified
	if rs.Namespace == "" {
		rs.Namespace = "realtime"
	}

	// NOTE: Replicas default is NOT set here.
	// A value of 0 is valid and means scale-to-zero.
	// If defaulting is needed, it should be done at the PodAutoscaler level.

	// NOTE: Selector defaults are typically generated from Template.Labels
	// by the reconciler, similar to how Deployment works.

	// NOTE: Template (PodTemplateSpec) defaults are handled by Kubernetes
	// when the pods are created. No need to default containers, resources, etc. here.
}
