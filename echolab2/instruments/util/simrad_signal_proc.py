# coding=utf-8

#     National Oceanic and Atmospheric Administration (NOAA)
#     Alaskan Fisheries Science Center (AFSC)
#     Resource Assessment and Conservation Engineering (RACE)
#     Midwater Assessment and Conservation Engineering (MACE)

#  THIS SOFTWARE AND ITS DOCUMENTATION ARE CONSIDERED TO BE IN THE PUBLIC DOMAIN
#  AND THUS ARE AVAILABLE FOR UNRESTRICTED PUBLIC USE. THEY ARE FURNISHED "AS IS."
#  THE AUTHORS, THE UNITED STATES GOVERNMENT, ITS INSTRUMENTALITIES, OFFICERS,
#  EMPLOYEES, AND AGENTS MAKE NO WARRANTY, EXPRESS OR IMPLIED, AS TO THE USEFULNESS
#  OF THE SOFTWARE AND DOCUMENTATION FOR ANY PURPOSE. THEY ASSUME NO RESPONSIBILITY
#  (1) FOR THE USE OF THE SOFTWARE AND DOCUMENTATION; OR (2) TO PROVIDE TECHNICAL
#  SUPPORT TO USERS.
"""
.. module:: echolab2.simrad_signal_proc

    :synopsis: Functions for processing Simrad EK80 data. Based on work
               by Chris Bassett, Lars Nonboe Anderson, Gavin Macaulay,
               Dezhang Chu, and many others.


| Developed by:  Rick Towler   <rick.towler@noaa.gov>
| National Oceanic and Atmospheric Administration (NOAA)
| Alaska Fisheries Science Center (AFSC)
| Midwater Assesment and Conservation Engineering Group (MACE)
|
| Author:
|       Rick Towler   <rick.towler@noaa.gov>
| Maintained by:
|       Rick Towler   <rick.towler@noaa.gov>
"""

import numpy as np

def create_ek80_tx(raw_data, calibration, return_indices=None):
    '''create_ek80_tx returns an array representing the ideal
    EK80 transmit signal computed using the parameters in the raw_data
    and calibration objects.
    '''

    # If we're not given specific indices, grab everything.
    if return_indices is None:
        return_indices = np.arange(raw_data.ping_time.shape[0])
    # Ensure that return_indices is a numpy array
    elif type(return_indices) is not np.ndarray:
        return_indices = np.array(return_indices, ndmin=1)

    #  create a dict to hold our calibration data parameters we need
    cal_parms = {'slope':None,
                 'transmit_power':None,
                 'pulse_duration':None,
                 'frequency_start':None,
                 'frequency_end':None,
                 'frequency':None,
                 'impedance':None,
                 'rx_sample_frequency':None,
                 'filters':None}

    #  now create a dict that will track these params
    last_parms = {'slope':None,
                 'transmit_power':None,
                 'pulse_duration':None,
                 'frequency_start':None,
                 'frequency_end':None,
                 'frequency':None,
                 'impedance':None,
                 'rx_sample_frequency':None,
                 'filters':None}

    # create the return array
    tx_data = np.empty(return_indices.shape[0], dtype=np.ndarray)

    # Iterate thru the return indices - We're
    for idx, ping_index in enumerate(return_indices):

        # Get the cal params we need for this ping
        for key in cal_parms:
            cal_parms[key] = calibration.get_parameter(raw_data, key, ping_index)

        # if this is CW data, we will not have the start/end params so we
        # set them to cal_parms['frequency']
        if cal_parms['frequency_start'] is None:
            cal_parms['frequency_start'] = cal_parms['frequency']
            cal_parms['frequency_end'] = cal_parms['frequency']

        # Check if this ping's Tx is the same as the last pings
        if last_parms['slope'] == None:
            #  this is the first ping, populate the initial values in last_parms
            for key in last_parms:
                last_parms[key] = cal_parms[key]
            compute_tx = True
        else:
            #  check if all params are the same
            #  assume they are and set compute_tx to False
            compute_tx = False
            #  now compare the params
            for key in last_parms:
                # if one of the params is different - compute_tx will be True
                compute_tx &= last_parms[key] != cal_parms[key]
                # after checking we update
                last_parms[key] = cal_parms[key]

        #  only generate, filter and decimate the new signal if needed
        if compute_tx:
            #  get the theoretical tx signal
            t, y = ek80_chirp(cal_parms['transmit_power'], cal_parms['frequency_start'],
                    cal_parms['frequency_end'], cal_parms['slope'],
                    cal_parms['pulse_duration'], cal_parms['impedance'],
                    cal_parms['rx_sample_frequency'])

            #  apply the stage 1 and stage 2 filters
            y = filter_and_decimate(y, cal_parms['filters'][0], [1, 2])

        #  store this ping's tx signal
        tx_data[idx] = y

    return tx_data


def compute_effective_pulse_duration(raw_data, calibration, return_indices=None):

    #  get the ideal transmit pulse
    tx_data = create_ek80_tx(raw_data, calibration, return_indices=return_indices)

    #  create the return array
    tau_eff = np.empty(tx_data.shape[0], dtype=np.float32)

    #  create some state variables
    last_tx = None
    last_tau_eff = None
    last_interval = None

    #  iterate thru the tx signals
    for idx, y in enumerate(tx_data):

        # check if this tx signal is the same as the last and
        if last_tx is not None:
            if np.array_equal(last_tx, y) and raw_data.sample_interval[idx] == last_interval:
                tau_eff[idx] = last_tau_eff
                last_interval = raw_data.sample_interval[idx]
        else:
            fs_dec = 1/ raw_data.sample_interval[idx]
            ptxa = np.abs(y) ** 2
            tau_eff[idx] =  np.sum(ptxa) / (np.max(ptxa) *fs_dec)
            last_interval = raw_data.sample_interval[idx]
            last_tau_eff = tau_eff[idx]
            last_tx = y

    return tau_eff


def filter_and_decimate(y, filters, stages):
    '''filter_and_decimate will apply one or more convolution and
    decimation operations on the provided data.

        y (complex) - The signal to be filtered
        filters (dict) - The filters dictionary associated with the signal
                         being filtered.
        stages (int, list) - A scalar integer or list of integers containing
                             the filter stage(s) to apply. Stages are applied
                             in the order they are added to the list.

    '''
    #  make sure stages is iterable - make it so if not.
    try:
        iter(stages)
    except Exception:
        stages = [stages]

    #  get the procided filter stages
    filter_stages = filters.keys()

    # iterate through the stages and apply filters in order provided
    for stage in stages:
        #  make sure this filter exists
        if not stage in filter_stages:
            raise ValueError("Filter stage " + str(stage) + " is not in the " +
                    "supplied filters dictionary.")

        # get the filter coefficients and decimation factor
        coefficients = filters[stage]['coefficients']
        decimation_factor = filters[stage]['decimation_factor']

        # apply filter
        y = np.convolve(y, coefficients)

        # and decimate
        y = y[0::decimation_factor]

    return y


def ek80_chirp(txpower, fstart, fstop, slope, tau, z, rx_freq):
    '''ek80_chirp returns a representation of the EK80 transmit signal
    as (time, amplitude) with a maximum amplitude of 1.

    This code was originally written in MATLAB by
        Chris Bassett - cbassett@uw.edu
        University of Washington Applied Physics Lab

    txpower (float) - The transmit power in watts
    fstart (float) - The starting Frequency of the tx signal obtained
                    from the raw file configuration datagram in Hz.
    fstart (float) - The starting Frequency of the tx signal obtained
                    from the raw file configuration datagram in Hz.
    slope (float) - The slope of the signal ramp up and ramp down
    tau (float) - The commanded transmit pulse length in s.
    z (float) - The transducer impedance obtained from the raw file
                configuration datagram in ohms.
    rx_freq (float) - the receiver A/D sampling frequency in Hz

    '''

    # Create transmit signal
    sf = 1.0 / rx_freq
    a  = np.sqrt((txpower / 4.0) * (2.0 * z))
    t = np.arange(0, tau, sf)
    nt = t.shape[0]
    nwtx = int(2 * np.floor(slope * nt))
    wtx_tmp = np.hanning(nwtx)
    nwtxh = int(np.round(nwtx / 2))
    wtx = np.concatenate([wtx_tmp[0:nwtxh], np.ones((nt - nwtx)), wtx_tmp[nwtxh:]])
    beta = (fstop - fstart) * (tau ** -1)
    chirp = np.cos(2.0 * np.pi * (beta / 2.0 * (t ** 2) + fstart * t))
    y_tmp = a * chirp * wtx

    # The transmit signal must have a max amplitude of 1
    y = y_tmp / np.max(np.abs(y_tmp))

    return t, y


def pulse_compression(p_data, raw_data, calibration, return_indices=None):
    '''pulse_compression applies a matched filter to the received signal using
    the simulated Tx signal as the filter template. This method will only apply
    the filter to FM pings. It does nothing to CW pings. The p_data object is
    modified in-place.
    '''

    # If we're not given specific indices, grab everything.
    if return_indices is None:
        return_indices = np.arange(raw_data.ping_time.shape[0])
    # Ensure that return_indices is a numpy array
    elif type(return_indices) is not np.ndarray:
        return_indices = np.array(return_indices, ndmin=1)

    # Check if we have any fm pings to process
    is_fm = raw_data.pulse_form[return_indices] > 0
    if np.any(is_fm):
        # we do have fm pings - get the indices for those fm pings
        fm_pings = return_indices[is_fm]
        # get the simulated tx signal for these pings
        tx_signal = create_ek80_tx(raw_data, calibration, return_indices=fm_pings)

        # apply match filter to these pings
        for p_idx, tx in enumerate(tx_signal):
            # create matched filter using tx signal for this ping
            tx_mf = np.flipud(np.conj(tx))
            ltx = len(tx_mf)
            tx_n = np.linalg.norm(tx) ** 2
            #compressed = np.empty(p_data.data[p_idx,:,0].shape, dtype=p_data.data.dtype)
            for q_idx in range(p_data.data[p_idx,:,:].shape[1]):
                compressed = np.convolve(p_data.data[p_idx,:,q_idx], tx_mf) / tx_n
                p_data.data[p_idx,:,q_idx] = compressed[ltx-1:]


