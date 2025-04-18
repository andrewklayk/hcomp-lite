import argparse
import os
import sys
import pandas as pd
from utils.load_folktables import load_folktables_torch
import numpy as np
import torch
from torch import tensor, nn
from torch.utils.data import TensorDataset, DataLoader

parent_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(os.path.dirname(parent_dir)))
        
from src.algos.sslpd import SSLPD
from src.algos.sw_sub import SwitchingSubgradient_unbiased
from src.algos.auglag import AugLagr
from src.algos.ghost import StochasticGhost

class SimpleNet(nn.Module):
    def __init__(self, in_shape, out_shape, dtype):
        super().__init__()
        self.linear_relu_stack = nn.Sequential(
            nn.Linear(in_shape, 64, dtype=dtype),
            nn.ReLU(),
            nn.Linear(64, 32, dtype=dtype),
            nn.ReLU(),
            nn.Linear(32, out_shape, dtype=dtype),
        )

    def forward(self, x):
        logits = self.linear_relu_stack(x)
        return logits

def one_sided_loss_constr(loss, net, c_data):
    w_inputs, w_labels = c_data[0]
    b_inputs, b_labels = c_data[1]
    w_outs = net(w_inputs)
    w_loss = loss(w_outs, w_labels.unsqueeze(1))
    b_outs = net(b_inputs)
    b_loss = loss(b_outs, b_labels.unsqueeze(1))

    return w_loss - b_loss

def roc_constraint(loss, net, c_data):
    w_inputs, w_labels = c_data[0]
    b_inputs, b_labels = c_data[1]
    w_outs = net(w_inputs)
    b_outs = net(b_inputs)
    
    # thresholds = 
    




if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(
                    prog='folktables exp')
    
    ### experiment parameters
    parser.add_argument('-alg', '--algorithm')
    parser.add_argument('-ne', '--num_exp', type=int)
    
    ### algorithm parameters
    parser.add_argument('-maxiter', '--maxiter', nargs='?', const=None, type=int)
    # ghost
    parser.add_argument('-alpha', '--geomp', nargs='?', const=0.2, default=0.2, type=float)
    parser.add_argument('-beta', '--beta', nargs='?', const=10, default=10, type=float)
    parser.add_argument('-rho', '--rho', nargs='?', const=0.8, default=0.8, type=float)
    parser.add_argument('-lambda', '--lam', nargs='?', const=0.5, default=0.5, type=float)
    parser.add_argument('-gamma0', '--gamma0', nargs='?', const=0.05, default=0.05, type=float)
    parser.add_argument('-zeta', '--zeta', nargs='?', const=0.3, default=0.3, type=float)
    parser.add_argument('-tau', '--tau', nargs='?', const=1, default=1, type=float)
    # parser.add_argument('-kappa_mode', '--kappa_mode', nargs='?', const='old')
    
    # parse args
    args = parser.parse_args()
    ALG_TYPE = args.algorithm
    EXP_NUM = args.num_exp
    
    if ALG_TYPE == 'sg':
        G_ALPHA = args.geomp
        MAXITER_GHOST = 1000 if args.maxiter is None else args.maxiter
        ghost_rho = args.rho
        ghost_beta = args.beta
        ghost_lambda = args.lam
        ghost_gamma0 = args.gamma0
        ghost_zeta = args.zeta
        ghost_tau = args.tau
    
    
    if torch.cuda.is_available():
        device = 'cuda'
        print('CUDA found')
    else:
        device = 'cpu'
        print('CUDA not found')
    device = 'cpu'
    
    print(f'{device = }')    
    torch.set_default_device(device)
    
    DTYPE = torch.float32

    DATASET_NAME = 'employment_az'
    FT_DATASET, FT_STATE = DATASET_NAME.split('_')
    torch.set_default_dtype(DTYPE)
    
    X_train, y_train, [w_idx_train, nw_idx_train], X_test, y_test, [w_idx_test, nw_idx_test] = load_folktables_torch(
        FT_DATASET, state=FT_STATE.upper(), random_state=0, make_unbalanced = False
    )
        
    X_train_tensor = tensor(X_train, dtype=DTYPE)
    y_train_tensor = tensor(y_train, dtype=DTYPE)
    train_ds = TensorDataset(X_train_tensor,y_train_tensor)
    print(f'Train data loaded: {DATASET_NAME}')
    
    # TODO: move to command line args
    # EXP_NUM = 7
    LOSS_BOUND = 0.005
    RUNTIME_LIMIT = 15
    UPDATE_LAMBDA = True
    # G_ALPHA = 0.3
    # ALG_TYPE = 'sg'
    BATCH_SIZE = 16
    # MAXITER_GHOST = 1500
    MAXITER_ALM = np.inf
    MAXITER_SSG = np.inf
    MAXITER_SSLALM = np.inf
    TEST_SKIP_ITERS = 1
    
    read_model = False
    
    saved_models_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'utils', 'saved_models'))
    directory = os.path.join(saved_models_path, DATASET_NAME,f'{LOSS_BOUND:.0E}')
    if ALG_TYPE.startswith('sg'):
        model_name = os.path.join(directory, f'{ALG_TYPE}_{LOSS_BOUND}_p{G_ALPHA}')
    else:
        model_name = os.path.join(directory, f'{ALG_TYPE}_{LOSS_BOUND}')
        
    
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    ftrial, ctrial, wtrial, ttrial, samples_trial = [], [], [], [], []
    
    # experiment loop
    for EXP_IDX in range(EXP_NUM):
        
        # torch.manual_seed(EXP_IDX)
        model_path = model_name + f'_trial{EXP_IDX}.pt'
        
        net = SimpleNet(in_shape=X_test.shape[1], out_shape=1, dtype=DTYPE).to(device)
        if read_model:
            net.load_state_dict(torch.load(model_path, weights_only=False, map_location=torch.device('cpu')))
        
        N = min(len(w_idx_train), len(nw_idx_train))
        
        
        if ALG_TYPE.startswith('swsg'):
            history = SwitchingSubgradient_unbiased(net, train_ds, w_idx_train, nw_idx_train,
                                                   loss_bound=LOSS_BOUND,
                                                   batch_size=BATCH_SIZE,
                                                   epochs=2,
                                                   ctol = LOSS_BOUND,
                                                   f_stepsize_rule='dimin',
                                                   f_stepsize=7e-1,
                                                   c_stepsize_rule='dimin',
                                                   c_stepsize=7e-1,
                                                   device=device,
                                                   seed=EXP_IDX)
        elif ALG_TYPE.startswith('sg'):
            history = StochasticGhost(net, train_ds, w_idx_train, nw_idx_train,
                                  geomp=G_ALPHA,
                                  stepsize_rule='inv_iter',
                                  zeta = ghost_zeta,
                                  gamma0 = ghost_gamma0,
                                  beta=ghost_beta,
                                  rho=ghost_rho,
                                  lamb = ghost_lambda,
                                  tau = ghost_tau,
                                  loss_bound=LOSS_BOUND,
                                  maxiter=MAXITER_GHOST,
                                  seed=EXP_IDX)
        elif ALG_TYPE.startswith('aug'):
            history = AugLagr(net, train_ds,
                              w_idx_train,
                              nw_idx_train,
                              batch_size=BATCH_SIZE,
                              loss_bound=LOSS_BOUND,
                              update_lambda=UPDATE_LAMBDA,
                              maxiter=MAXITER_ALM,
                              device=device,
                              seed=EXP_IDX)
        elif ALG_TYPE.startswith('sslalm'):
            history = SSLPD(net, train_ds, w_idx_train, nw_idx_train, loss_bound=LOSS_BOUND,
                         lambda_bound = 100,
                         rho = 1,
                         mu = 2.,
                         tau = 1e-3,
                         beta = 0.1,
                         eta = 5e-3,
                         max_iter=MAXITER_SSLALM,
                         device=device,
                         seed=EXP_IDX)
        ## SAVE RESULTS ##
        ftrial.append(pd.Series(history['loss']))
        ctrial.append(history['constr'])
        wtrial.append(history['w'])
        ttrial.append(history['time'])
        samples_trial.append(pd.Series(history['n_samples']))
        
        # Save the model
        
        torch.save(net.state_dict(), model_path)
        print('')
    
    # Save DataFrames to CSV files
    utils_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'utils', 'exp_results'))
    if not os.path.exists(utils_path):
        os.makedirs(utils_path)
    
    ftrial = pd.concat(ftrial, keys=range(len(ftrial)))
    ctrial = pd.concat(ctrial, keys=range(len(ctrial)))
    samples_trial = pd.concat(samples_trial, keys=range(len(ctrial)))
    
    if ALG_TYPE.startswith('sg'):
        fname = f'{ALG_TYPE}_{DATASET_NAME}_{LOSS_BOUND}_{G_ALPHA}'
    else:
        fname = f'{ALG_TYPE}_{DATASET_NAME}_{LOSS_BOUND}'
    print(f'Saving to: {fname}')
    ftrial.to_csv(os.path.join(utils_path, fname + '_ftrial.csv'))
    ctrial.to_csv(os.path.join(utils_path, fname + '_ctrial.csv'))
    samples_trial.to_csv(os.path.join(utils_path, fname + '_samples.csv'))
    
    print('----')
    # df(n_iter, n_trials)
    wlen = max([len(tr) for tr in wtrial])
    index = pd.MultiIndex.from_product([['train', 'test'], np.arange(wlen), np.arange(EXP_NUM)], names=('is_train', 'iteration', 'trial'))
    full_stats = pd.DataFrame(index=index, columns=['Loss', 'C1', 'C2', 'SampleSize', 'time'])
    full_stats.sort_index(inplace=True)
    
    net = SimpleNet(in_shape=X_test.shape[1], out_shape=1, dtype=DTYPE).cuda()
    loss_fn = nn.BCEWithLogitsLoss()
    
    X_test_tensor = tensor(X_test, dtype=DTYPE).cuda()
    y_test_tensor = tensor(y_test, dtype=DTYPE).cuda()
    
    X_test_w = X_test_tensor[w_idx_test]
    y_test_w = y_test_tensor[w_idx_test]
    X_test_nw = X_test_tensor[nw_idx_test]
    y_test_nw = y_test_tensor[nw_idx_test]
    
    X_train_w = X_train_tensor[w_idx_train]
    y_train_w = y_train_tensor[w_idx_train]
    X_train_nw = X_train_tensor[nw_idx_train]
    y_train_nw = y_train_tensor[nw_idx_train]
    
    save_train = False
    with torch.inference_mode():
        for exp_idx in range(EXP_NUM):
            weights_to_eval = wtrial[exp_idx][::TEST_SKIP_ITERS]
            for alg_iteration, w in enumerate(weights_to_eval):

                print(f'{exp_idx} | {alg_iteration}', end='\r')
                net.load_state_dict(w)
                
                if save_train:
                    outs = net(X_train_tensor)
                    loss = loss_fn(outs, y_train_tensor.unsqueeze(1)).detach().cpu().numpy()
                    
                    c1 = one_sided_loss_constr(loss_fn, net, [(X_train_w, y_train_w), (X_train_nw, y_train_nw)]).detach().cpu().numpy()
                    c2 = -c1
                    # pandas multiindex bug(?) workaround
                    full_stats.loc['train'].at[alg_iteration, exp_idx] = {'Loss': loss, 'C1': c1, 'C2': c2, 'SampleSize': 1}
                    
                outs = net(X_test_tensor)
                loss = loss_fn(outs, y_test_tensor.unsqueeze(1)).detach().cpu().numpy()
                
                c1 = one_sided_loss_constr(loss_fn, net, [(X_test_w, y_test_w), (X_test_nw, y_test_nw)]).detach().cpu().numpy()
                c2 = -c1
                
                full_stats.loc['test'].at[alg_iteration, exp_idx] = {
                    'Loss': loss,
                    'C1': c1,
                    'C2': c2,
                    'SampleSize': samples_trial[exp_idx][alg_iteration],
                    'time': ttrial[exp_idx][alg_iteration]}
            
    if ALG_TYPE.startswith('sg'):
        fname = f'{ALG_TYPE}_{DATASET_NAME}_{LOSS_BOUND}_{G_ALPHA}.csv'
    else:
        fname = f'{ALG_TYPE}_{DATASET_NAME}_{LOSS_BOUND}.csv'
    print(f'Saving to: {fname}')
    full_stats.to_csv(os.path.join(utils_path, fname))