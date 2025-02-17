// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Partial code comes from other Microsoft employee.
#include "clip_tokenizer.hpp"
#include "narrow.h"
#include <optional>

KernelClipBpeTokenizer::KernelClipBpeTokenizer(const OrtApi& api, const OrtKernelInfo& info)
    : BaseKernel(api, info) {
  std::string vocab = ort_.KernelInfoGetAttribute<std::string>(&info, "vocab");
  if (vocab.empty()) {
    ORTX_CXX_API_THROW("vocabulary shouldn't be empty.", ORT_INVALID_ARGUMENT);
  }

  std::string merges = ort_.KernelInfoGetAttribute<std::string>(&info, "merges");
  if (merges.empty()) {
    ORTX_CXX_API_THROW("merges shouldn't be empty.", ORT_INVALID_ARGUMENT);
  }

  if (!TryToGetAttribute<int64_t>("padding_length", padding_length_)) {
    padding_length_ = -1;
  }

  if (padding_length_ != -1 && padding_length_ <= 0) {
    ORTX_CXX_API_THROW("padding_length should be more than 0 or equal -1", ORT_INVALID_ARGUMENT);
  }

  std::stringstream vocabu_stream(vocab);
  std::stringstream merges_stream(merges);
  bbpe_tokenizer_ = std::make_shared<VocabData>();
  bbpe_tokenizer_->Load(vocabu_stream, merges_stream, "<|endoftext|>", "<|startoftext|>\n<|endoftext|>");
}

std::vector<int64_t> KernelClipBpeTokenizer::Tokenize(ustring& input, int64_t max_length, bool compute_offset_mapping,
                                                      std::list<OffsetMappingType>& offset_map) const {
  std::vector<int64_t> res;
  std::list<std::pair<int, int>> byte_list;

  WhiteSpaceClean(input);

  if (IsEmptyUString(input)) {
    return res;
  }
  // Add BOS token to result
  res.push_back(bbpe_tokenizer_->GetEncoding("<|startoftext|>"));

  // Convert to lowercase
  std::transform(input.begin(), input.end(), input.begin(), [](char32_t c) { return static_cast<char32_t>(ToLower(c)); });

  // Parse input
  auto special_token_split_res = bbpe_tokenizer_->SplitBySpecialTokens(input);
  TokenWithRegularExp regcmp;

  for (auto& seg_id : special_token_split_res) {
    if (static_cast<int64_t>(res.size()) >= max_length) break;

    if (seg_id.second != -1) {
      res.push_back(seg_id.second);
      continue;
    }

    auto cur_input = std::move(seg_id.first);
    // Note: keep ptr to make sure the string_view is valid in the following process
    const char32_t* ptr = cur_input.c_str();
    regcmp.Set(ptr);

    size_t offset = 0;
    OffsetMappingType offset_mapping;

    if (compute_offset_mapping) {
      // Add offset mapping for BOS token
      offset_mapping.push_back(std::make_pair(0, 0));
    }

    while (static_cast<int64_t>(res.size()) < max_length) {
      auto [b, tok] = regcmp.GetNextToken();
      if (!b) break;

      std::string utf8_token = std::string(ustring(tok));

      if (compute_offset_mapping) {
        // Handle special case for offset mapping
        if (utf8_token.at(0) == ' ') {
          offset++;
        }
      }

      // Whitespace clean
      utf8_token.erase(std::remove(utf8_token.begin(), utf8_token.end(), ' '), utf8_token.end());

      // Get byte encodings prior to performing BPE
      byte_list.clear();
      for (int i = 0; i < utf8_token.length(); i++) {
        if (i == utf8_token.length() - 1) {
          std::string boundary(1, utf8_token[i]);
          byte_list.push_back(std::make_pair(bbpe_tokenizer_->GetEncoding(boundary + "</w>"), 1));
        } else {
          byte_list.push_back(std::make_pair(bbpe_tokenizer_->ByteEncoder()[static_cast<unsigned char>(utf8_token[i])], 1));
        }
      }

      // Perform BPE
      bbpe_tokenizer_->bpe(byte_list);

      // Add output to result
      for (auto p : byte_list) {
        if (static_cast<int64_t>(res.size()) >= max_length) {
          break;
        }

        res.push_back(p.first);

        if (compute_offset_mapping) {
          offset_mapping.emplace_back(std::make_pair(offset, ort_extensions::narrow<size_t>(offset + p.second)));
          offset += p.second;
        }
      }
    }

    if (compute_offset_mapping) {
      // Add offset mapping for EOS token
      offset_mapping.emplace_back(std::make_pair(0, 0));

      // Add offset mappings for input in this instance to list of offset mappings for all inputs
      offset_map.emplace_back(offset_mapping);
    }
  }
  // Add EOS token to result
  res.push_back(bbpe_tokenizer_->GetEncoding("<|endoftext|>"));
  return res;
}

void KernelClipBpeTokenizer::Compute(const ortc::Tensor<std::string>& input,
                                     ortc::Tensor<int64_t>& tokenize_output,
                                     std::optional<ortc::Tensor<int64_t>*> attention_mask,
                                     std::optional<ortc::Tensor<int64_t>*> offset_mapping) const {
  // Setup inputs
  std::vector<std::string> str_input{input.Data()};
  std::list<OffsetMappingType> offset_map;
  const auto& input_dim = input.Shape();

  std::vector<std::vector<int64_t>> tokenize_results;

  // Only compute offset mapping if optional output for it exists.
  bool compute_offset_mapping = false;
  if (offset_mapping.has_value()) {
    compute_offset_mapping = true;
  }

  for (auto& str : str_input) {
    ustring ustr = ustring(str);
    tokenize_results.emplace_back(Tokenize(ustr, padding_length_ < 0 ? INT64_MAX : padding_length_,
                                           compute_offset_mapping, offset_map));
  }

  size_t max_length = 0;
  if (padding_length_ == -1) {
    for (auto& res : tokenize_results) {
      max_length = std::max(max_length, res.size());
    }
  } else {
    max_length = static_cast<size_t>(padding_length_);
  }

  std::vector<int64_t> output_dim = input_dim;
  output_dim.push_back(max_length);

  std::vector<int64_t> offset_dim = output_dim;
  offset_dim.push_back(2);  // tuple of offsets for each input id

  auto* token = tokenize_output.Allocate(output_dim);
  if (attention_mask.has_value()) {
    auto* mask = (*attention_mask)->Allocate(output_dim);
    int idx = 0;
    for (auto& res : tokenize_results) {
      for (int64_t id : res) {
        mask[idx] = 1;
        idx++;
      }

      for (size_t i = res.size(); i < max_length; i++) {
        mask[idx] = 0;
        idx++;
      }
    }
  }
  if (offset_mapping.has_value()) {
    auto* offset = (*offset_mapping)->Allocate(offset_dim);
    int idx2 = 0;
    for (auto& res : offset_map) {
      for (auto& mapping : res) {
        offset[idx2] = mapping.first;
        idx2++;
        offset[idx2] = mapping.second;
        idx2++;
      }
    }
  }
  int idx = 0;
  // currently HF uses "<|endoftext|>" as default pad token
  int pad_token = bbpe_tokenizer_->GetEncoding("<|endoftext|>");
  for (auto& res : tokenize_results) {
    for (int64_t id : res) {
      token[idx] = id;
      idx++;
    }

    for (size_t i = res.size(); i < max_length; i++) {
      token[idx] = pad_token;
      idx++;
    }
  }
}
