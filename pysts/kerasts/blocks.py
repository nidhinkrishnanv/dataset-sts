"""
Predefined Keras Graph blocks that represent common model components.
"""

from __future__ import division
from __future__ import print_function

from keras.layers.convolutional import Convolution1D, MaxPooling1D
from keras.layers.core import Activation, Dense, Dropout, Flatten, LambdaMerge
from keras.layers.embeddings import Embedding
from keras.layers.recurrent import GRU
from keras.regularizers import l2

import pysts.nlp as nlp


def embedding(model, glove, vocab, s0pad, s1pad, dropout, trainable=True):
    """ The universal sequence input layer.

    Declare inputs si0, si1, f0, f1 (vectorized sentences and NLP flags)
    and generate outputs e0, e1 representing vector sequences, and e0_, e1_
    with dropout applied.  Returns the vector dimensionality. """

    for m, p in [(0, s0pad), (1, s1pad)]:
        model.add_input('si%d'%(m,), input_shape=(p,), dtype='int')
        model.add_input('f%d'%(m,), input_shape=(p, nlp.flagsdim))
    model.add_shared_node(name='emb', inputs=['si0', 'si1'], outputs=['e0[0]', 'e1[0]'],
                          layer=Embedding(input_dim=vocab.size(), input_length=p,
                                          output_dim=glove.N, mask_zero=True,
                                          weights=[vocab.embmatrix(glove)], trainable=trainable))
    for m in [0, 1]:
        model.add_node(name='e%d'%(m,), inputs=['e%d[0]'%(m,), 'f%d'%(m,)], merge_mode='concat', layer=Activation('linear'))
    N = glove.N + nlp.flagsdim

    model.add_shared_node(name='embdrop', inputs=['e0', 'e1'], outputs=['e0_', 'e1_'],
                          layer=Dropout(dropout, input_shape=(N,)))

    return N


def rnn_input(model, N, spad, dropout=3/4, sdim=2, rnnbidi=True, return_sequences=False,
              rnn=GRU, rnnact='tanh', rnninit='glorot_uniform'):
    """ An RNN layer that takes sequence of embeddings e0_, e1_ and
    processes them using an RNN + dropout.

    If return_sequences=False, it returns just the final hidden state of the RNN;
    otherwise, it return a sequence of contextual token embeddings instead.
    At any rate, the output layers are e0s_, e1s_.
    """
    if rnnbidi:
        model.add_shared_node(name='rnnf', inputs=['e0_', 'e1_'], outputs=['e0sf', 'e1sf'],
                              layer=rnn(input_dim=N, output_dim=int(N*sdim), input_length=spad,
                                        init=rnninit, activation=rnnact,
                                        return_sequences=return_sequences))
        model.add_shared_node(name='rnnb', inputs=['e0_', 'e1_'], outputs=['e0sb', 'e1sb'],
                              layer=rnn(input_dim=N, output_dim=int(N*sdim), input_length=spad,
                                        init=rnninit, activation=rnnact,
                                        return_sequences=return_sequences, go_backwards=True))
        model.add_node(name='e0s', inputs=['e0sf', 'e0sb'], merge_mode='sum', layer=Activation('linear'))
        model.add_node(name='e1s', inputs=['e1sf', 'e1sb'], merge_mode='sum', layer=Activation('linear'))

    else:
        model.add_shared_node(name='rnn', inputs=['e0_', 'e1_'], outputs=['e0s', 'e1s'],
                              layer=rnn(input_dim=N, output_dim=int(N*sdim), input_length=spad,
                                        init=rnninit, activation=rnnact,
                                        return_sequences=return_sequences))

    model.add_shared_node(name='rnndrop', inputs=['e0s', 'e1s'], outputs=['e0s_', 'e1s_'],
                          layer=Dropout(dropout, input_shape=(spad, N) if return_sequences else (N,)))


def cnnsum_input(model, N, spad, dropout=3/4, l2reg=1e-4,
                 cnninit='glorot_uniform', cnnact='tanh',
                 cdim={1: 1/2, 2: 1/2, 3: 1/2, 4: 1/2, 5: 1/2}):
    """ An CNN pooling layer that takes sequence of embeddings e0_, e1_ and
    processes them using a CNN + max-pooling to produce a single "summary
    embedding" (*NOT* a sequence of embeddings).

    The layer can apply multiple convolutions of different widths; the
    convolution dimensionality is denoted by the cdim dict, keyed by width
    and containing the number of filters.  The resulting summary embedding
    dimensionality is sum of N*cdim values (the convolutions are concatenated),
    returned by this function for your convenience.

    The output layers are e0s_, e1s_.
    """
    Nc = 0
    for fl, cd in cdim.items():
        nb_filter = int(N*cd)
        model.add_shared_node(name='aconv%d'%(fl,),
                              inputs=['e0_', 'e1_'], outputs=['e0c%d'%(fl,), 'e1c%d'%(fl,)],
                              layer=Convolution1D(input_shape=(spad, N),
                                                  nb_filter=nb_filter, filter_length=fl,
                                                  activation=cnnact, W_regularizer=l2(l2reg),
                                                  init=cnninit))
        model.add_shared_node(name='apool%d[0]'%(fl,),
                              inputs=['e0c%d'%(fl,), 'e1c%d'%(fl,)], outputs=['e0s%d[0]'%(fl,), 'e1s%d[0]'%(fl,)],
                              layer=MaxPooling1D(pool_length=int(spad - fl + 1)))
        model.add_shared_node(name='apool%d[1]'%(fl,),
                              inputs=['e0s%d[0]'%(fl,), 'e1s%s[0]'%(fl,)], outputs=['e0s%d'%(fl,), 'e1s%d'%(fl,)],
                              layer=Flatten(input_shape=(1, nb_filter)))
        Nc += nb_filter

    if len(cdim) > 1:
        model.add_node(name='e0s', inputs=['e0s%d'%(fl,) for fl in cdim.keys()], merge_mode='concat', layer=Activation('linear'))
        model.add_node(name='e1s', inputs=['e1s%d'%(fl,) for fl in cdim.keys()], merge_mode='concat', layer=Activation('linear'))
    else:
        model.add_node(name='e0s', input='e0s%d'%(cdim.keys()[0],), layer=Activation('linear'))
        model.add_node(name='e1s', input='e1s%d'%(cdim.keys()[0],), layer=Activation('linear'))
    model.add_node(name='e0s_', input='e0s', layer=Dropout(dropout))
    model.add_node(name='e1s_', input='e1s', layer=Dropout(dropout))

    return Nc


# Match point scoring (scalar output) callables.  Each returns the layer name.
# This is primarily meant as an output layer, but could be used also for
# example as an attention mechanism.

def dot_ptscorer(model, inputs, Ddim, N, l2reg, pfx='out'):
    """ Score the pair using just dot-product, that is elementwise
    multiplication and sum.  The dot-product is natural because it
    measures the relative directions of vectors, being essentially
    a non-normalized cosine similarity. """
    # (The Activation is a nop, merge_mode is the important part)
    model.add_node(name=pfx+'dot', inputs=inputs, layer=Activation('linear'), merge_mode='dot', dot_axes=1)
    return pfx+'dot'


def mlp_ptscorer(model, inputs, Ddim, N, l2reg, pfx='out'):
    """ Element-wise features from the pair fed to an MLP. """
    model.add_node(name=pfx+'sum', inputs=inputs, layer=Activation('linear'), merge_mode='sum')
    model.add_node(name=pfx+'mul', inputs=inputs, layer=Activation('linear'), merge_mode='mul')

    model.add_node(name=pfx+'hdn', inputs=[pfx+'sum', pfx+'mul'], merge_mode='concat',
                   layer=Dense(output_dim=int(N*Ddim), W_regularizer=l2(l2reg), activation='sigmoid'))
    model.add_node(name=pfx+'mlp', input=pfx+'hdn',
                   layer=Dense(output_dim=1, W_regularizer=l2(l2reg)))
    return pfx+'mlp'


def cat_ptscorer(model, inputs, Ddim, N, l2reg, pfx='out'):
    """ Just train a linear classifier (weighed sum of elements) on concatenation
    of inputs.  You may pass also just a single input (which may make sense
    if you for example process s1 "with regard to s0"). """
    model.add_node(name=pfx+'cat', inputs=inputs, merge_mode='concat',
                   layer=Dense(output_dim=1, W_regularizer=l2(l2reg)))


def absdiff_merge(model, layers):
    """ Merging two layers into one, via element-wise subtraction and then taking absolute value.

    Example of usage: model.add_node(name="diff", layer=absdiff_merge(["e0_", "e1_"]))

    TODO: The more modern way appears to be to use "join" merge mode and Lambda layer.
    """
    def diff(X):
        if len(X)!=2:
            raise ValueError("")
        return K.abs(X[0]-X[1])

    def output_shape(input_shapes):
        return input_shapes[0]

    return LambdaMerge([model.nodes[l] for l in layers], diff, output_shape)
