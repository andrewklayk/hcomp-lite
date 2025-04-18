from typing import Tuple,Callable, List
import torch.utils.data.dataloader
import numpy as np
import scipy as sp
from copy import deepcopy
from scipy.optimize import linprog
from qpsolvers import solve_qp
import autoray as ar
import timeit
from itertools import cycle
from .utils import net_grads_to_tensor, net_params_to_tensor
import cvxpy as cp
import torch

m_det = 0
m_st = 2
import timeit
constr_sampling_interval = 1
max_runtime = 15

def one_sided_loss_constr(loss, net, c_data):
    w_inputs, w_labels = c_data[0]
    b_inputs, b_labels = c_data[1]
    w_outs = net(w_inputs)
    if w_labels.ndim == 0:
        w_labels = w_labels.reshape(1)
        b_labels = b_labels.reshape(1)
    else:
        w_labels = w_labels.unsqueeze(1)
        b_labels = b_labels.unsqueeze(1)
    w_loss = loss(w_outs, w_labels)
    b_outs = net(b_inputs)
    b_loss = loss(b_outs, b_labels)

    return w_loss - b_loss


def project(x, m):
    # for i in range(1,m+1):
    #     if x[-i] < 0:
    #         x[-i] = 0
    return x


# def SwitchingSubgradient_slack(net: torch.nn.Module, data, w_ind, b_ind, loss_bound,
#             batch_size=8,
#             max_runtime=np.inf,
#             ctol = 5e-4,
#             start_lambda=None,
#             device='cpu',
#             epochs=2,
#             seed = 42):
        
#     history = {'loss': [],
#                'constr': [],
#                'w': []}
    
#     # slack variables
#     slack_vars = torch.zeros(2, requires_grad=True)
    
#     c1 = lambda net, d, s: one_sided_loss_constr(loss_fn, net, d) - loss_bound + s
#     c2 = lambda net, d, s: -one_sided_loss_constr(loss_fn, net, d) - loss_bound + s
    
#     data_w = torch.utils.data.Subset(data, w_ind)
#     data_b = torch.utils.data.Subset(data, b_ind)
    
#     loss_fn = torch.nn.BCEWithLogitsLoss()
#     loss_eval = None
#     c_t = None
#     run_start = timeit.default_timer()
#     for epoch in range(epochs):
        
#         gen = torch.Generator(device=device)
#         gen.manual_seed(seed+epoch)
#         loader = torch.utils.data.DataLoader(data, batch_size, shuffle=True, generator=gen)
#         loader_w = cycle(torch.utils.data.DataLoader(data_w, batch_size, shuffle=True, generator=gen))
#         loader_b = cycle(torch.utils.data.DataLoader(data_b, batch_size, shuffle=True, generator=gen))
        
#         for iteration, f_sample in enumerate(loader):
            
#             current_time = timeit.default_timer()
#             if max_runtime > 0 and current_time - run_start >= max_runtime:
#                 print(current_time - run_start)
#                 return
            
#             net.zero_grad()
            
#             eta_t = 1e-3
            
#             # generate sample of constraints
#             cw_sample = next(loader_w)
#             cb_sample = next(loader_b)
#             c_sample = [cw_sample, cb_sample]
#             c1_eval = c1(net, c_sample, slack_vars[0])
#             c2_eval = c2(net, c_sample, slack_vars[1])
#             c_t = torch.concat([
#                 c1_eval.reshape(1),
#                 c2_eval.reshape(1)
#             ])
#             c_max = torch.max(c_t)

#             x_t = torch.concat([
#                 net_params_to_tensor(net, flatten=True, copy=True),
#                 slack_vars
#             ])
            
#             if c_max >= ctol:
#                 # generate stochastic gradient
#                 c_max.backward()
#                 c_grad = net_grads_to_tensor(net)
#                 c_grad = torch.concat([c_grad, slack_vars.grad])
#                 x_t1 = project(x_t - eta_t*c_grad, m=2)
#             else:
#                 f_inputs, f_labels = f_sample
#                 outputs = net(f_inputs)       
#                 if f_labels.dim() < outputs.dim():
#                     f_labels = f_labels.unsqueeze(1)
#                 loss_eval = loss_fn(outputs, f_labels)
#                 loss_eval.backward()
#                 f_grad = net_grads_to_tensor(net)
#                 f_grad = torch.concat([f_grad, torch.zeros(2)]) # add zeros for slack vars
                
#                 x_t1 = project(x_t - eta_t*f_grad, m=2)
            
#             start = 0
#             with torch.no_grad():
#                 w = net_params_to_tensor(net, flatten=False, copy=False)
#                 for i in range(len(w)):
#                     end = start + w[i].numel()
#                     w[i].set_(x_t1[start:end].reshape(w[i].shape))
#                     start = end

#                 for i in range(len(slack_vars)):
#                     slack_vars[i] = x_t1[i-len(slack_vars)]
            
#             if loss_eval is not None and c_t is not None:
#                 print(f"""{iteration}|{loss_eval.detach().cpu().numpy()}|{c_t.detach().cpu().numpy()}|{slack_vars.detach().cpu().numpy()}""", end='\r')
#             history['w'].append(deepcopy(net.state_dict()))
        
#     ######################
#     ### POSTPROCESSING ###    
#     ######################
#     return history










def SwitchingSubgradient(net: torch.nn.Module, data, w_ind, b_ind, loss_bound,
            batch_size=8,
            max_runtime=np.inf,
            # ctol_rule = 'dimin',
            ctol = 1e-1,
            # ctol_min = 1e-5,
            f_stepsize_rule = 'dimin',
            f_stepsize = 5e-1,
            c_stepsize_rule = 'adaptive',
            c_stepsize = None,
            device='cpu',
            epochs=1,
            seed = 42):
        
    history = {'loss': [],
               'constr': [],
               'w': [],
               'time': []}
    
    c1 = lambda net, d: one_sided_loss_constr(loss_fn, net, d) - loss_bound
    c2 = lambda net, d: -one_sided_loss_constr(loss_fn, net, d) - loss_bound
    
    data_w = torch.utils.data.Subset(data, w_ind)
    data_b = torch.utils.data.Subset(data, b_ind)
    
    loss_fn = torch.nn.BCEWithLogitsLoss()
    loss_eval = None
    c_t = None
    run_start = timeit.default_timer()
    current_time = timeit.default_timer()
    
    f_eta_t = f_stepsize
    c_eta_t = c_stepsize
    
    f_iters = 0
    c_iters = 0
    for epoch in range(epochs):
        
        if current_time - run_start >= max_runtime:
            break
        
        gen = torch.Generator(device=device)
        gen.manual_seed(seed+epoch)
        loader = torch.utils.data.DataLoader(data, batch_size, shuffle=True, generator=gen)
        loader_w = cycle(torch.utils.data.DataLoader(data_w, batch_size, shuffle=True, generator=gen))
        loader_b = cycle(torch.utils.data.DataLoader(data_b, batch_size, shuffle=True, generator=gen))
        
        for iteration, f_sample in enumerate(loader):
            
            current_time = timeit.default_timer()
            history['time'].append(current_time - run_start)
            if max_runtime > 0 and current_time - run_start >= max_runtime:
                print(current_time - run_start)
                break
            
            net.zero_grad()
                
            # if ctol_rule == 'dimin':
            #     ctol_t = ctol/np.sqrt(iteration+1)
            #     if ctol_t < ctol_min:
            #         ctol_t = ctol_min
            # elif ctol_rule == 'const':
            #     ctol_t = ctol
            
            # generate sample of constraints
            cw_sample = next(loader_w)
            cb_sample = next(loader_b)
            c_sample = [cw_sample, cb_sample]
            c1_eval = c1(net, c_sample)
            c2_eval = c2(net, c_sample)
            c_t = torch.concat([
                c1_eval.reshape(1),
                c2_eval.reshape(1)
            ])
            c_max = torch.max(c_t)
            history['constr'].append(c_max.cpu().detach().numpy())

            x_t = net_params_to_tensor(net, flatten=True, copy=True)
            
            if c_max >= ctol:
                c_iters += 1
                c_max.backward()
                c_grad = net_grads_to_tensor(net)
                if c_stepsize_rule == 'adaptive':
                    c_eta_t = c_max / torch.norm(c_grad)**2
                elif c_stepsize_rule == 'const':
                    c_eta_t = c_stepsize
                
                x_t1 = project(x_t - c_eta_t*c_grad, m=2)
            else:
                f_iters += 1
                f_inputs, f_labels = f_sample
                outputs = net(f_inputs)
                if f_labels.dim() < outputs.dim():
                    f_labels = f_labels.unsqueeze(1)
                loss_eval = loss_fn(outputs, f_labels)
                loss_eval.backward()
                history['loss'].append(loss_eval.cpu().detach().numpy())
                f_grad = net_grads_to_tensor(net)
                
                if f_stepsize_rule == 'dimin':
                    f_eta_t = f_stepsize / np.sqrt(f_iters)
                elif f_stepsize_rule == 'const':
                    f_eta_t = f_stepsize
                x_t1 = project(x_t - f_eta_t*f_grad, m=2)
            
            start = 0
            with torch.no_grad():
                w = net_params_to_tensor(net, flatten=False, copy=False)
                for i in range(len(w)):
                    end = start + w[i].numel()
                    w[i].set_(x_t1[start:end].reshape(w[i].shape))
                    start = end
            
            if loss_eval is not None and c_t is not None:
                with np.printoptions(precision=6, suppress=True):
                    print(f'{iteration:5}|{loss_eval.detach().cpu().numpy()}|{c_t.detach().cpu().numpy()}', end='\r')
            history['w'].append(deepcopy(net.state_dict()))
        
    ######################
    ### POSTPROCESSING ###    
    ######################
    print('\n')
    print(c_iters)
    return history



def SwitchingSubgradient_unbiased(net: torch.nn.Module, data, w_ind, b_ind, loss_bound,
            batch_size=8,
            max_runtime=np.inf,
            # ctol_rule = 'dimin',
            ctol = 1e-1,
            # ctol_min = 1e-5,
            f_stepsize_rule = 'dimin',
            f_stepsize = 5e-1,
            c_stepsize_rule = 'adaptive',
            c_stepsize = None,
            device='cpu',
            epochs=1,
            seed = 42):
        
    history = {'loss': [],
               'constr': [],
               'w': [],
               'time': []}
    
    c1 = lambda net, d: one_sided_loss_constr(loss_fn, net, d) - loss_bound
    c2 = lambda net, d: -one_sided_loss_constr(loss_fn, net, d) - loss_bound
    
    c = [c1, c2]
    
    data_w = torch.utils.data.Subset(data, w_ind)
    data_b = torch.utils.data.Subset(data, b_ind)
    
    loss_fn = torch.nn.BCEWithLogitsLoss()
    loss_eval = None
    c_t = None
    run_start = timeit.default_timer()
    current_time = timeit.default_timer()
    
    f_eta_t = f_stepsize
    c_eta_t = c_stepsize
    
    f_iters = 0
    c_iters = 0
    for epoch in range(epochs):
        
        if current_time - run_start >= max_runtime:
            break
        
        gen = torch.Generator(device=device)
        gen.manual_seed(seed+epoch)
        loader = torch.utils.data.DataLoader(data, batch_size, shuffle=True, generator=gen)
        loader_w = cycle(torch.utils.data.DataLoader(data_w, batch_size, shuffle=True, generator=gen))
        loader_b = cycle(torch.utils.data.DataLoader(data_b, batch_size, shuffle=True, generator=gen))
        
        for iteration, f_sample in enumerate(loader):
            
            current_time = timeit.default_timer()
            history['time'].append(current_time - run_start)
            if max_runtime > 0 and current_time - run_start >= max_runtime:
                print(current_time - run_start)
                break
            
            net.zero_grad()
                
            # if ctol_rule == 'dimin':
            #     ctol_t = ctol/np.sqrt(iteration+1)
            #     if ctol_t < ctol_min:
            #         ctol_t = ctol_min
            # elif ctol_rule == 'const':
            #     ctol_t = ctol
            
            # generate sample of constraints
            cw_sample = next(loader_w)
            cb_sample = next(loader_b)
            c_sample = [cw_sample, cb_sample]
            # calc constraints and update multipliers (line 3)
            with torch.no_grad():
                c_t = torch.cat([ci(net, c_sample).reshape(1) for i, ci in enumerate(c)])
                c_max = torch.max(c_t)
            history['constr'].append(c_max.cpu().detach().numpy())

            x_t = net_params_to_tensor(net, flatten=True, copy=True)
            
            if c_max >= ctol:
                c_iters += 1
                # calculate grad on an independent sample
                cw_sample = next(loader_w)
                cb_sample = next(loader_b)
                c_sample = [cw_sample, cb_sample]
                c_t2 = torch.concat([ci(net, c_sample).reshape(1) for i, ci in enumerate(c)])
                c_max2 = torch.max(c_t2)
                c_max2.backward()
                c_grad = net_grads_to_tensor(net)
                if c_stepsize_rule == 'adaptive':
                    c_eta_t = c_max / torch.norm(c_grad)**2
                elif c_stepsize_rule == 'const':
                    c_eta_t = c_stepsize
                elif c_stepsize_rule == 'dimin':
                    c_eta_t = c_stepsize / np.sqrt(c_iters)
                
                x_t1 = project(x_t - c_eta_t*c_grad, m=2)
            else:
                f_iters += 1
                f_inputs, f_labels = f_sample
                outputs = net(f_inputs)
                if f_labels.dim() < outputs.dim():
                    f_labels = f_labels.unsqueeze(1)
                loss_eval = loss_fn(outputs, f_labels)
                loss_eval.backward()
                history['loss'].append(loss_eval.cpu().detach().numpy())
                f_grad = net_grads_to_tensor(net)
                
                if f_stepsize_rule == 'dimin':
                    f_eta_t = f_stepsize / np.sqrt(f_iters)
                elif f_stepsize_rule == 'const':
                    f_eta_t = f_stepsize
                x_t1 = project(x_t - f_eta_t*f_grad, m=2)
            
            start = 0
            with torch.no_grad():
                w = net_params_to_tensor(net, flatten=False, copy=False)
                for i in range(len(w)):
                    end = start + w[i].numel()
                    w[i].set_(x_t1[start:end].reshape(w[i].shape))
                    start = end
            
            if loss_eval is not None and c_t is not None:
                with np.printoptions(precision=6, suppress=True):
                    print(f'{iteration:5}|{loss_eval.detach().cpu().numpy()}|{c_t.detach().cpu().numpy()}', end='\r')
            history['w'].append(deepcopy(net.state_dict()))
        
    ######################
    ### POSTPROCESSING ###    
    ######################
    print('\n')
    print(c_iters)
    return history