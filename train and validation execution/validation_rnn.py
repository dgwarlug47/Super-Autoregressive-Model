try:
    from helpers import sample_returns, find_alpha2, comparison
    from trial_helper import save_cumulative_data, trial_summary_extractor
except:
    print('notebook_style')


def rnn_validate_and_collect_performance_metrics(model, validation_data_sets, real_returns, data_preparation_hyper_parameters, model_hyper_parameters, cums):
    # validates the model in both the validation_data_sets, collects cumulative data
    # data_preparation_hyper_parameters was already explained in the docs folder.
    # model_hyper_parameters was already explained in the docs folder.
    # real_returns jas dimensions (validation_num_of_securities, num_days)
    import time
    import torch
    import numpy as np
    time6 = time.clock()
    """ extracting the data from data_preparation_hyper_parameters and model_hyper_parameters"""
    validation_train_data = validation_data_sets[0]
    validation_test_data = validation_data_sets[1]
    seq_length = data_preparation_hyper_parameters['seq_length']
    device = data_preparation_hyper_parameters['device']
    d = data_preparation_hyper_parameters['n_bins']
    lower_bound = data_preparation_hyper_parameters['lower_bound']
    upper_bound = data_preparation_hyper_parameters['upper_bound']
    testing_benchmark = model_hyper_parameters['testing_benchmark']
    using_middle_returns = model_hyper_parameters['using_middle_returns']
    using_discretized_bins = model_hyper_parameters['using_discretized_bins']
    alphas = model_hyper_parameters['alphas']

    with torch.no_grad():
        validation_num_of_securities = validation_train_data.shape[0]

        """  the bins variable is to help the computation of the artificial returns from the respective bins of each data. """
        bins = np.linspace(lower_bound, upper_bound, d - 1)
        # pnl_list, pos_list, and prob_list have dimensions [2 (to differentiate train and test set), num_of_securities, num_of_data points processes until the respective moment.]
        # actually prob_list is a litte bit different, becuase it has a last of dimension of: num_bins
        """ Initializing the aggregate_data, in order to save it and analyze it later. """
        aggregate_losses = [[], []]
        aggregate_KL_divergences = [np.empty([validation_num_of_securities, 0]), np.empty([validation_num_of_securities, 0])]
        aggregate_MSE_divergences = [np.empty([validation_num_of_securities, 0]), np.empty([validation_num_of_securities, 0])]
        pnl_list = [np.empty([validation_num_of_securities, 0]), np.empty([validation_num_of_securities, 0])]
        pos_list = [np.empty([validation_num_of_securities, 0]), np.empty([validation_num_of_securities, 0])]
        rets_list = [np.empty([validation_num_of_securities, 0]), np.empty([validation_num_of_securities, 0])]
        # prob_list = [np.empty([num_of_securities,0,d]), np.empty([num_of_securities,0, d])]

        targets_indexes = 0
        for train_or_test in range(2):
            data = [validation_train_data, validation_test_data][train_or_test]
            validation_seq_length = seq_length
            label = data[:, :, :, 0].int()
            # data has dimensions: (num_securities, num_of all data points of a single security / seq_length, seq_length, the number of features)
            for i in range(data.shape[1]):
                # x_inp has dimensions (num_of_securities, seq_length, num_of_features)
                # all data from x_inp come from time step i
                x_inp = data[:, i, :, :]
                logits = model.get_logits_from_neural_net_output(model.get_neural_net_output_from_input(x_inp, 'validation'))
                # out has dimensions [num_of_securities, seq_length, num_bins]
                future_labels = label[:, i, 1:]

                # future_labels has dimensions [num_of_securities, seq_length - 1]
                if i != data.shape[1] - 1:
                    current_seq_length = validation_seq_length
                    # current_logits and logits are almost the same, the only difference
                    # is that current_logits changes a bit when  i == data.shape - 1
                    # it removes the last time step prediction since there is no way to predict it.
                    current_logits = logits.clone().to(device)
                    last_label_of_sequence = label[:, i + 1, [0]]
                    future_labels = torch.cat((future_labels, last_label_of_sequence), dim=1)

                else:
                    current_seq_length = validation_seq_length - 1
                    current_logits = logits[:, : - 1, :].clone().to(device)
                current_flattened_logits = current_logits.view(-1, d)

                loss = model.get_loss_from_neural_net_output(current_logits, future_labels).item()
                # important to note, than in this instance, loss is just a number, it is the average of the all losses over all predictions. Just like we do in the training mode.

                fit_train_distribution = np.repeat(np.expand_dims(data_preparation_hyper_parameters['train_true_distribution'], axis=0),
                                                   repeats=[validation_num_of_securities * current_seq_length], axis=0)

                import warnings
                warnings.simplefilter("ignore")
                from torch.nn import KLDivLoss
                KLD = KLDivLoss(reduce=False)
                KL_divergence = KLD(torch.nn.functional.log_softmax(current_flattened_logits, dim=1),
                                    torch.FloatTensor(fit_train_distribution).to(device)).sum(axis=1).view(validation_num_of_securities, -1).cpu().detach().numpy()

                from torch.nn import MSELoss
                MSE = MSELoss(reduce=False)
                MSE_divergence = MSE(torch.softmax(current_flattened_logits, dim=1),
                                     torch.FloatTensor(fit_train_distribution).to(device)).sum(axis=1).view(validation_num_of_securities, -1).cpu().detach().numpy()

                """ part 1 probabilities estimation"""
                prob = torch.softmax(logits, dim=2)
                prob = prob.cpu().detach().numpy()
                # prob has dimensions(num_of_securities, seq_length, num_bins)
                # part 2 returns per class estimation, needs to be checked , may have an issue with dims
                classes_rets = np.repeat(np.expand_dims(sample_returns(np.arange(d), bins, using_middle_returns), 0), repeats=validation_num_of_securities * current_seq_length, axis=0)
                # part 3 maximize p_i x ln (1+alpha+ret) to get the position
                prob_fit_for_find_alpha2 = prob[:, range(current_seq_length), :].reshape(-1, d)
                # print("the classes_rets", classes_rets.shape)
                pos1 = find_alpha2(prob_fit_for_find_alpha2, classes_rets, alphas)

                comparing_different_find_alpha_methods = False
                if comparing_different_find_alpha_methods:
                    pos2 = find_alpha2(prob_fit_for_find_alpha2, classes_rets)
                    print(pos2.shape)
                    comparison(pos1, pos2, prob_fit_for_find_alpha2, classes_rets)

                if not testing_benchmark:
                    pos = pos1.reshape([validation_num_of_securities, current_seq_length])
                else:
                    pos = np.repeat(np.repeat(np.expand_dims(np.array([2.0]), axis=0), axis=0, repeats=validation_num_of_securities), axis=1, repeats=current_seq_length)

                # pos has dimensions [num_of_securites, 1]

                # part 4 next day return

                if using_discretized_bins:
                    flattened_future_labels = future_labels.clone().view(-1).long()
                    ret = sample_returns(np.array(flattened_future_labels.cpu()), bins, using_middle_returns).reshape([validation_num_of_securities, current_seq_length])
                else:
                    ret = real_returns[:, (1 + targets_indexes):(1 + targets_indexes + current_seq_length)]
                targets_indexes = targets_indexes + validation_seq_length
                pnl = ret * pos

                """ In this part we update the lists and aggregators. """
                aggregate_KL_divergences[train_or_test] = np.concatenate((aggregate_KL_divergences[train_or_test], KL_divergence), axis=1)
                aggregate_MSE_divergences[train_or_test] = np.concatenate((aggregate_MSE_divergences[train_or_test], MSE_divergence), axis=1)
                aggregate_losses[train_or_test].append(loss)
                pnl_list[train_or_test] = np.concatenate((pnl_list[train_or_test], pnl), axis=1)
                pos_list[train_or_test] = np.concatenate((pos_list[train_or_test], pos), axis=1)
                rets_list[train_or_test] = np.concatenate((rets_list[train_or_test], ret), axis=1)
                # prob_list[train_or_test] = np.concatenate((prob_list[train_or_test], prob), axis=1)

        """ We will now extract all of the important metrics from the aggregates data"""
        trial_summary = trial_summary_extractor(pos_list, pnl_list, [aggregate_losses, aggregate_MSE_divergences, aggregate_KL_divergences])

        save_cumulative_data(data_preparation_hyper_parameters, model_hyper_parameters, cums, trial_summary, pnl_list, pos_list)

        time7 = time.clock()
        print("End of Validation process, total time: ", time7 - time6)
        return trial_summary
