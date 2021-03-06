from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import torch
from torch import nn
from ..random_variables import GaussianRandomVariable
from .grid_inducing_variational_gp import GridInducingVariationalGP


class AdditiveGridInducingVariationalGP(GridInducingVariationalGP):

    def __init__(
        self, grid_size, grid_bounds, n_components, mixing_params=False, sum_output=True
    ):
        super(AdditiveGridInducingVariationalGP, self).__init__(grid_size, grid_bounds)
        self.n_components = n_components
        self.sum_output = sum_output

        # Resize variational parameters to have one size per component
        variational_mean = self.variational_mean
        chol_variational_covar = self.chol_variational_covar
        variational_mean.data.resize_(*([n_components] + list(variational_mean.size())))
        chol_variational_covar.data.resize_(
            *([n_components] + list(chol_variational_covar.size()))
        )

        # Mixing parameters
        if mixing_params:
            self.register_parameter(
                "mixing_params",
                nn.Parameter(torch.Tensor(n_components).fill_(1. / n_components)),
                bounds=(-2, 2),
            )

    def _compute_grid(self, inputs):
        n_data, n_components, n_dimensions = inputs.size()
        inputs = inputs.transpose(0, 1).contiguous().view(
            n_components * n_data, n_dimensions
        )
        interp_indices, interp_values = super(
            AdditiveGridInducingVariationalGP, self
        )._compute_grid(
            inputs
        )
        interp_indices = interp_indices.view(n_components, n_data, -1)
        interp_values = interp_values.view(n_components, n_data, -1)

        if hasattr(self, "mixing_params"):
            interp_values = interp_values.mul(
                self.mixing_params.unsqueeze(1).unsqueeze(2)
            )
        return interp_indices, interp_values

    def _initalize_variational_parameters(self, prior_output):
        batch_size = self.chol_variational_covar.size(0)
        mean_init = prior_output.mean().data
        mean_init += mean_init.new(mean_init.size()).normal_().mul_(1e-1)

        chol_covar_init = torch.eye(mean_init.size(-1)).type_as(mean_init)
        chol_covar_init = chol_covar_init.unsqueeze_(0).repeat(batch_size, 1, 1)
        chol_covar_init += chol_covar_init.new(chol_covar_init.size()).normal_().mul_(
            1e-1
        )

        self.variational_mean.data.copy_(mean_init)
        self.chol_variational_covar.data.copy_(chol_covar_init)

    def covar_diag(self, inputs):
        n_data, n_components, n_dimensions = inputs.size()
        inputs = inputs.transpose(0, 1).contiguous()
        return super(AdditiveGridInducingVariationalGP, self).covar_diag(inputs)

    def prior_output(self):
        out = super(AdditiveGridInducingVariationalGP, self).prior_output()
        mean = out.mean()
        covar = out.covar().repeat(self.n_components, 1, 1)
        return GaussianRandomVariable(mean, covar)

    def __call__(self, inputs, **kwargs):
        if inputs.ndimension() == 1:
            inputs = inputs.unsqueeze(-1).unsqueeze(-1)
        elif inputs.ndimension() == 2:
            inputs = inputs.unsqueeze(-1)
        elif inputs.ndimension() != 3:
            raise RuntimeError("AdditiveGridInducingVariationalGP expects a 3d tensor.")

        n_data, n_components, n_dimensions = inputs.size()
        if n_dimensions != self.grid.size(0):
            raise RuntimeError(
                "The number of dimensions should match the inducing points "
                " number of dimensions."
            )
        if n_components != self.n_components:
            raise RuntimeError(
                "The number of components should match the number specified."
            )
        if n_dimensions != 1:
            raise RuntimeError(
                "At the moment, AdditiveGridInducingVariationalGP only supports "
                "1d (Toeplitz) interpolation."
            )

        output = super(AdditiveGridInducingVariationalGP, self).__call__(
            inputs, **kwargs
        )
        if self.sum_output:
            mean = output.mean().sum(0)
            covar = output.covar().sum_batch()
            return GaussianRandomVariable(mean, covar)
        else:
            return output
