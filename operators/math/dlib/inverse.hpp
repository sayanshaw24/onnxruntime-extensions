// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

#pragma once

#include <dlib/matrix.h>
#include "ocos.h"

void inverse(const ortc::TensorT<float>& input,
             ortc::TensorT<float>& output) {
  auto& dimensions = input.Shape();
  if (dimensions.size() != 2) {
    throw std::runtime_error("Only 2-d matrix supported.");
  }
  const float* X = input.Data();
  float* out = output.Allocate(dimensions);

  dlib::matrix<float> dm_x(dimensions[0], dimensions[1]);
  std::copy(X, X + dm_x.size(), dm_x.begin());
  dlib::matrix<float> dm = dlib::inv(dm_x);
  memcpy(out, dm.steal_memory().get(), dm_x.size() * sizeof(float));
}
