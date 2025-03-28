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
        
from src.algos.auglag import AugLagr

class SimpleNet(nn.Module):
    def __init__(self, in_shape, out_shape):
        super().__init__()
        self.linear_relu_stack = nn.Sequential(
            nn.Linear(in_shape, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, out_shape),
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




if __name__ == "__main__":
    
    DATASET_NAME = 'employment'
    
    saved_models_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'utils', 'saved_models'))
    directory = os.path.join(saved_models_path, DATASET_NAME)
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    X_train, y_train, [w_idx_train, nw_idx_train], X_test, y_test, [w_idx_test, nw_idx_test] = load_folktables_torch(
        'employment', state='AL', random_state=42, make_unbalanced = False
    )
        
    X_train_tensor = tensor(X_train, dtype=torch.float)
    y_train_tensor = tensor(y_train, dtype=torch.float)
    train_ds = TensorDataset(X_train_tensor,y_train_tensor)
    train_loader = DataLoader(train_ds, batch_size=16, shuffle=True)
    
    # TODO: move to command line args
    EXP_NUM = 10
    LOSS_BOUND = 0.005
    RUNTIME_LIMIT = 15
    ALG_NAME = 'al'
    UPDATE_LAMBDA = True
    
       
    ftrial, ctrial, wtrial = [], [], []
    
    # experiment loop
    for EXP_IDX in range(EXP_NUM):
        
        net = SimpleNet(in_shape=X_test.shape[1], out_shape=1)
        
        N = min(len(w_idx_train), len(nw_idx_train))
        
        history = AugLagr(net, train_ds, w_idx_train, nw_idx_train, batch_size=8, loss_bound=LOSS_BOUND, maxiter=np.inf,
                          update_lambda=UPDATE_LAMBDA)
        
        ## SAVE RESULTS ##
        ftrial.append(history['loss'])
        ctrial.append(history['constr'])
        wtrial.append(history['w'])
        

        # Save the model
        model_path = os.path.join(directory, f'{ALG_NAME}_{LOSS_BOUND}_trial{EXP_IDX}.pt')
        torch.save(net.state_dict(), model_path)
        print('')
    
    # Save DataFrames to CSV files
    utils_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'utils', 'exp_results'))
    if not os.path.exists(utils_path):
        os.makedirs(utils_path)
    
    print('----')
    # df(n_iter, n_trials)
    wlen = max([len(tr) for tr in wtrial])
    index = pd.MultiIndex.from_product([['train', 'test'], np.arange(wlen), np.arange(EXP_NUM)], names=('is_train', 'iteration', 'trial'))
    full_stats = pd.DataFrame(index=index, columns=['Loss', 'C1', 'C2'])
    full_stats.sort_index(inplace=True)
    
    net = SimpleNet(in_shape=X_test.shape[1], out_shape=1)
    loss_fn = nn.BCEWithLogitsLoss()
    
    X_test_tensor = tensor(X_test, dtype=torch.float)
    y_test_tensor = tensor(y_test, dtype=torch.float)
    
    X_test_w = X_test_tensor[w_idx_test]
    y_test_w = y_test_tensor[w_idx_test]
    X_test_nw = X_test_tensor[nw_idx_test]
    y_test_nw = y_test_tensor[nw_idx_test]
    
    X_train_w = X_train_tensor[w_idx_train]
    y_train_w = y_train_tensor[w_idx_train]
    X_train_nw = X_train_tensor[nw_idx_train]
    y_train_nw = y_train_tensor[nw_idx_train]
    
    every_x_iter = 1
    
    with torch.no_grad():
        for exp_idx in range(EXP_NUM):
            for alg_iteration, w in enumerate(wtrial[exp_idx][::every_x_iter]):
                print(f'{exp_idx} | {alg_iteration}', end='\r')
                net.load_state_dict(w)
                
                outs = net(X_train_tensor)
                loss = loss_fn(outs, y_train_tensor.unsqueeze(1)).detach().numpy()
                
                c1 = one_sided_loss_constr(loss_fn, net, [(X_train_w, y_train_w), (X_train_nw, y_train_nw)]).detach().numpy()
                c2 = -c1
                # pandas multiindex bug(?) workaround
                full_stats.loc['train'].at[alg_iteration, exp_idx] = {'Loss': loss, 'C1': c1, 'C2': c2}
                
                outs = net(X_test_tensor)
                loss = loss_fn(outs, y_test_tensor.unsqueeze(1)).detach().numpy()
                
                c1 = one_sided_loss_constr(loss_fn, net, [(X_test_w, y_test_w), (X_test_nw, y_test_nw)]).detach().numpy()
                c2 = -c1
                
                full_stats.loc['test'].at[alg_iteration, exp_idx] = {'Loss': loss, 'C1': c1, 'C2': c2}
            
    alg_type = 'AUG' if UPDATE_LAMBDA else 'PEN'
    full_stats.to_csv(os.path.join(utils_path, f'{alg_type}_{DATASET_NAME}_{LOSS_BOUND}_{1}_REPORT.csv'))